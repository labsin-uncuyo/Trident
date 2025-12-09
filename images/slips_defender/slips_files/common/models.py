# SPDX-FileCopyrightText: 2021 Sebastian Garcia <sebastian.garcia@agents.fel.cvut.cz>
#  SPDX-License-Identifier: GPL-2.0-only
from abc import ABC
from functools import reduce
from typing import Dict

import tensorflow as tf
from pathlib import Path
import numpy as np
from copy import deepcopy

from common.config import Config
from common.utils import deserialize, serialize
from sklearn.metrics import log_loss

tf.config.run_functions_eagerly(True)


def get_ad_model(dropout=0.2):
    model = tf.keras.Sequential(
        [
            tf.keras.layers.Input(shape=(36)),
            tf.keras.layers.Dense(32, activation="elu"),
            tf.keras.layers.Dropout(dropout),
            tf.keras.layers.Dense(20, activation="elu"),
            tf.keras.layers.Dropout(dropout),
            tf.keras.layers.Dense(10, activation="sigmoid"),
            tf.keras.layers.Dropout(dropout),
            tf.keras.layers.Dense(20, activation="elu"),
            tf.keras.layers.Dropout(dropout),
            tf.keras.layers.Dense(32, activation="elu"),
            tf.keras.layers.Dropout(dropout),
            tf.keras.layers.Dense(36, activation="elu"),
        ]
    )
    model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=0.001), loss="mse")
    return model


def get_triplet_loss_model():
    inputs = tf.keras.Input(shape=(36))
    pos = tf.keras.Input(shape=(36))
    neg = tf.keras.Input(shape=(36))

    ae = AutoEncoder()
    outputs = ae(inputs, pos, neg)

    loss_fn = tf.keras.losses.MeanSquaredError()
    optimizer = tf.keras.optimizers.Adam(learning_rate=1e-3)

    model = tf.keras.Model([inputs, pos, neg], outputs)
    model.compile(optimizer=optimizer, loss=loss_fn, run_eagerly=True)

    return model


def get_classification_model(
    model_path: Path,
    n_classes=2,
    encoder_lr=0.001,
    classifier_lr=0.1,
    freeze_encoder_layers=False,
    dropout=0.3,
):
    encoder = _load_encoder_model(model_path)
    model = _add_classification_layers(
        encoder, n_classes, encoder_lr, classifier_lr, freeze_encoder_layers, dropout
    )

    return model


class AutoEncoder(tf.keras.layers.Layer):
    """Combines the encoder and decoder into an end-to-end model for training."""

    def __init__(self, **kwargs):
        super(AutoEncoder, self).__init__(**kwargs)
        # self.original_dim = 36
        self.encoder = Encoder(latent_dim=10)
        self.decoder = Decoder(36)
        self.margin = 2.0

    def call(self, inputs, positive, negative):
        z = self.encoder(inputs)
        p = self.encoder(positive)
        n = self.encoder(negative)
        reconstructed = self.decoder(z)

        # Add Triplet loss.
        # The triplet loss is defined as:
        # L(A, P, N) = max(‖f(A) - f(P)‖² - ‖f(A) - f(N)‖² + margin, 0)

        ap_distance = tf.reduce_sum(tf.square(z - p))
        an_distance = tf.reduce_sum(tf.square(z - n))

        triplet_loss = ap_distance - an_distance
        triplet_loss = tf.maximum(triplet_loss + self.margin, 0.0)
        # triplet_loss = (ap_distance + tf.maximum(0.0, (10. - an_distance)/10.)) / 2.

        self.add_loss(triplet_loss)
        # self.add_metric(triplet_loss, name="triplet_loss", aggregation="mean")

        return reconstructed


class _LossTracker(tf.keras.losses.Loss):
    def __init__(self):
        super().__init__()
        self.loss_functions = []

    def register_loss(self, loss):
        self.loss_functions.append(loss)

    def call(self, y_true, y_pred):
        return sum(
            (loss_fun(y_true, y_pred) for loss_fun in self.loss_functions),
            start=tf.zeros_like(y_true),
        )


class FeelModel(tf.keras.Model, ABC):
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.input_size = config.model.input_size

        if config.model.optimizer == "Adam":
            self.optimizer = tf.keras.optimizers.Adam(
                learning_rate=config.model.learning_rate
            )
        elif config.model.optimizer == "SGD":
            self.optimizer = tf.keras.optimizers.SGD(
                learning_rate=config.model.learning_rate
            )

        self.loss_tracker = _LossTracker()

    def register_loss_function(self, lossFunction: tf.keras.losses.Loss):
        self.loss_tracker.register_loss(lossFunction)

    def compile(self, **kwargs):
        super(FeelModel, self).compile(self.optimizer, loss=self.loss_tracker, **kwargs)
        self.predict(np.zeros((1, self.input_size)))


class ProximalLoss(tf.keras.losses.Loss):
    """
    Proximal loss is used in the FedProx method. It penalizes the models in clients
    for diverging from the last received global model. This is implemented by capturing the
    `set_weights` method which always saves the copy of the new weights. During training
    these saved weights are compared to the current weights of the models and square loss
    is used.
    """

    def __init__(self, model: FeelModel, mu: float, tracker=None):
        super().__init__()
        self.model = model
        self.mu = mu
        self.previous_weights = model.get_weights()
        self.tracker = tracker
        self._capture_set_weights()

    def call(self, y_true, y_pred):
        prox_loss = 0
        for w, w_t in zip(self.model.get_weights(), self.previous_weights):
            if not w.any():
                continue
            prox_loss += tf.norm(w - w_t)
        prox_loss *= self.mu * 0.5
        if self.tracker:
            self.tracker.update_state(prox_loss)
        return prox_loss

    def _capture_set_weights(self):
        set_weights_method = self.model.set_weights

        def _set_weights(weights):
            set_weights_method(weights)
            self.prev_weights = deepcopy(weights)

        self.model.set_weights = _set_weights


class SimpelAutoEncoder(FeelModel):
    def __init__(self, config: Config):
        super().__init__(config)
        latent_dim = config.model.latent_dim
        self.decoder = Decoder(36, latent_dim=latent_dim)
        self.encoder = Encoder(36, latent_dim=latent_dim)
        self.register_loss_function(tf.keras.losses.MeanSquaredError())

    def call(self, inputs, training=None, mask=None):
        embedded = self.encoder(
            inputs,
        )
        reconstructed = self.decoder(embedded)
        return reconstructed


class MultiHeadAutoEncoder(FeelModel):
    def __init__(self, config: Config):
        self.disable_classifier = config.model.disable_classifier

        super().__init__(config)
        latent_dim = config.model.latent_dim
        self.variational = config.model.variational
        self.encoder = Encoder(latent_dim=latent_dim)
        self.tracker = MetricsTracker(
            classification=not self.disable_classifier,
            reconstruction=not config.model.disable_reconstruction,
            kl=self.variational,
            proximal=config.model.proximal,
        )

        if self.variational:
            self.z_mean = tf.keras.layers.Dense(latent_dim, name="z_mean")
            self.z_log_var = tf.keras.layers.Dense(latent_dim, name="z_log_var")
            self.sampling = SamplingLayer()

        self.decoder = Decoder(36)
        self.decoder.trainable = False

        self.classifier = ClassifierHead(config.model.classifier_hidden, 2)
        self.classifier.trainable = not self.disable_classifier

        self.multihead_loss = MultiHeadLoss(
            self.tracker,
            variational=config.model.variational,
            disable_classifier=config.model.disable_classifier,
            disable_reconstruction=config.model.disable_reconstruction,
        )
        self.register_loss_function(self.multihead_loss)

        if config.model.proximal:
            self.register_loss_function(
                ProximalLoss(self, config.model.mu, self.tracker.prox_loss)
            )

    def call(self, inputs, training=None, mask=None):
        X_true, y_true = inputs[:, :-1], inputs[:, -1]
        embedded = self.embed(X_true)
        if self.variational:
            z_mean = self.z_mean(embedded)
            z_log_var = self.z_log_var(embedded)
            embedded = self.sampling([z_mean, z_log_var])

        reconstructed = self.decoder(embedded[y_true == 0])

        n_benign, dim = reconstructed.shape
        n_mal = y_true.shape[0] - n_benign

        ben_mask = y_true == 0
        mal_mask = y_true == 1
        ben_mask_diag = tf.linalg.tensor_diag(tf.cast(ben_mask, "float32"))
        mal_mask_diag = tf.linalg.tensor_diag(tf.cast(mal_mask, "float32"))

        ben_mask_matrix = tf.boolean_mask(ben_mask_diag, ben_mask, axis=0)
        mal_mask_matrix = tf.boolean_mask(mal_mask_diag, mal_mask, axis=0)

        reconstructed_all = tf.transpose(mal_mask_matrix) @ (
            tf.ones((n_mal, dim)) * -10
        )
        reconstructed_all += tf.transpose(ben_mask_matrix) @ reconstructed

        out = [reconstructed_all, embedded]
        if not self.disable_classifier:
            y_pred = self.classifier(embedded)
            out.append(y_pred)

        if self.variational:
            out += [z_mean, z_log_var]

        return tf.concat(out, axis=1)

    @property
    def metrics(self):
        return self.tracker.get_trackers()

    def predict(self, inputs, **kwargs):
        z = self.embed(inputs)
        reconstructed = self.decoder(z)
        y_pred = self.classifier(z)

        return tf.concat([reconstructed, y_pred], axis=1)  # .numpy()

    def embed(self, inputs):
        embedded = self.encoder(inputs)
        if self.variational:
            z_mean = self.z_mean(embedded)
            z_log_var = self.z_log_var(embedded)
            embedded = self.sampling([z_mean, z_log_var])
        return embedded

    def get_weights(self):
        weights = super().get_weights()
        if self.disable_classifier:
            cls_layers = len(self.classifier.weights)
            for i, w in enumerate(weights[-cls_layers:]):
                weights[-cls_layers + i] = np.zeros_like(w)
        return weights

    def set_weights(self, weights):
        super().set_weights(weights)
        # self.predict(np.zeros((32, 36)))
        self.prev_weights = deepcopy(weights)

    def eval(self, X, y_true):
        predict = self.predict(X)
        X_pred, y_pred = predict[:, :-1], predict[:, -1]
        mse = np.mean(np.power(X - X_pred, 2), axis=1)
        return mse, y_pred, log_loss(y_true, y_pred)


class MetricsTracker:
    def __init__(
        self,
        *,
        classification: bool = False,
        reconstruction: bool = False,
        kl: bool = False,
        proximal: bool = False,
    ):
        total = tf.keras.metrics.Mean(name="total_loss")
        self._trackers: Dict[tf.keras.metrics.Mean] = {total.name: total}
        if classification:
            classification = tf.keras.metrics.Mean(name="class_loss")
            self._trackers[classification.name] = classification
        if reconstruction:
            reconstruction = tf.keras.metrics.Mean(name="rec_loss")
            self._trackers[reconstruction.name] = reconstruction
        if kl:
            kl = tf.keras.metrics.Mean(name="kl_loss")
            self._trackers[kl.name] = kl
        if proximal:
            proximal = tf.keras.metrics.Mean(name="prox_loss")
            self._trackers[proximal.name] = proximal

    def __add__(self, other: "MetricsTracker"):
        for tracker_name in self._trackers.keys():
            self._trackers[tracker_name].merge_state(other._trackers[tracker_name])
        return self

    def serialize(self):
        return serialize(self._trackers)

    def get_trackers(self):
        return list(self._trackers.values())

    @staticmethod
    def deserialize(state):
        tracker = MetricsTracker()
        tracker._trackers = deserialize(state)
        return tracker

    def __getattr__(self, item):
        if item := self._trackers.get(item):
            return item
        else:
            raise ValueError(f"Tracker {item} not registered")


class MultiHeadLoss(tf.keras.losses.Loss):
    def __init__(
        self,
        tracker: MetricsTracker,
        dim=36,
        variational=False,
        disable_classifier=False,
        disable_reconstruction=False,
    ):
        super().__init__()
        self.dim = dim
        self.bce = tf.keras.losses.BinaryCrossentropy(from_logits=True)
        self.mce = tf.keras.losses.MeanSquaredError()
        self.tracker = tracker
        self.variational = variational
        self.disable_classifier = disable_classifier
        self.disable_reconstruction = disable_reconstruction
        self._epsilon = 1e-9

    def call(self, inputs_true, inputs_pred):
        """

        @param inputs_true: Expects the shape of the array be [X, y]; shape = (n_samples, dim + 1)
        @param inputs_pred: Expect the shape of array to be [X_reconstructed, X_embedded, y];
        shape = (n_samples, dim + embedding_dim + 1)
        @return:
        """
        total_loss = 0
        if self.variational:
            latent_dim = 10
            z_mean = inputs_pred[:, -2 * latent_dim : -latent_dim]
            z_log_var = inputs_pred[:, -latent_dim:]
            inputs_pred = inputs_pred[:, : -2 * latent_dim]
            kl_loss = 0.5 * (
                tf.reduce_sum(tf.square(z_mean), axis=1)
                + tf.reduce_sum(tf.exp(z_log_var), axis=1)
                - tf.reduce_sum(z_log_var, axis=1)
                - 1
            )
            kl_loss = tf.reduce_mean(kl_loss)
            self.tracker.kl_loss.update_state(kl_loss)
            total_loss += kl_loss

        label_true = inputs_true[:, -1]
        label_pred = inputs_pred[:, -1]

        reconstructed_true = inputs_true[:, : self.dim]
        reconstructed_pred = inputs_pred[:, : self.dim]

        reconstructed_true_ben = tf.boolean_mask(
            reconstructed_true, label_true == 0, axis=0
        )
        reconstructed_pred_ben = tf.boolean_mask(
            reconstructed_pred, label_true == 0, axis=0
        )

        cross_entropy_loss = (
            self.bce(label_true, label_pred) if not self.disable_classifier else 0.0
        )
        if tf.math.is_nan(cross_entropy_loss):
            cross_entropy_loss = self._epsilon
        self.tracker.class_loss.update_state(cross_entropy_loss)
        total_loss += cross_entropy_loss

        reconstruction_loss = (
            self.mce(reconstructed_true_ben, reconstructed_pred_ben)
            if not self.disable_reconstruction
            else 0.0
        )
        self.tracker.rec_loss.update_state(reconstruction_loss)

        total_loss += reconstruction_loss
        self.tracker.total_loss.update_state(total_loss)

        return total_loss


class ClassifierHead(tf.keras.layers.Layer):
    def __init__(self, in_dim=10, n_classes=2, dropout=0.3):
        super().__init__()
        self.cl1 = tf.keras.layers.Dense(in_dim, name="DenseCls1", activation="elu")
        self.drop = tf.keras.layers.Dropout(dropout, name="ClsDroupout")
        self.cl2 = tf.keras.layers.Dense(
            n_classes if n_classes != 2 else 1, name="DenseCls2"
        )  # , activation='sigmoid')

    def call(self, X, *args, training=None, **kwargs):
        X_prime = X
        X_prime = self.cl1(X_prime)
        X_prime = self.drop(X_prime, training)
        X_prime = self.cl2(X_prime)
        return X_prime


class SamplingLayer(tf.keras.layers.Layer):
    """Uses (z_mean, z_log_var) to sample z, the vector encoding"""

    def call(self, inputs, *args, **kwargs):
        z_mean, z_log_var = inputs
        batch = tf.shape(z_mean)[0]
        dim = tf.shape(z_mean)[1]
        epsilon = tf.keras.backend.random_normal(shape=(batch, dim))
        return z_mean + tf.exp(0.5 * z_log_var) * epsilon


class Encoder(tf.keras.layers.Layer):
    def __init__(self, latent_dim=10, **kwargs):
        super(Encoder, self).__init__(**kwargs)
        self.l1 = tf.keras.layers.Dense(32, activation="elu")
        self.drop = tf.keras.layers.Dropout(0.3)
        self.l2 = tf.keras.layers.Dense(20, activation="elu")
        self.drop = tf.keras.layers.Dropout(0.3)
        self.l3 = tf.keras.layers.Dense(latent_dim, activation="sigmoid")
        self.drop = tf.keras.layers.Dropout(0.3)
        self.layer_list = [self.l1, self.drop, self.l2, self.drop, self.l3]

    def call(self, inputs, *args, training=None, **kwargs):
        x = self.l1(inputs)
        x = self.drop(x, training)
        x = self.l2(x)
        x = self.drop(x, training)
        z = self.l3(x)
        return z

    def sequential(self):
        return tf.keras.Sequential(
            [
                self.l1,
                self.drop,
                self.l2,
                self.drop,
                self.l3,
            ]
        )


class Decoder(tf.keras.layers.Layer):
    """Converts z, the encoded digit vector, back into a readable digit."""

    def __init__(self, original_dim=36, **kwargs):
        super(Decoder, self).__init__(**kwargs)
        self.l1 = tf.keras.layers.Dense(20, activation="elu")
        self.drop = tf.keras.layers.Dropout(0.3)
        self.l2 = tf.keras.layers.Dense(32, activation="elu")
        self.drop = tf.keras.layers.Dropout(0.3)
        self.l3 = tf.keras.layers.Dense(original_dim, activation="elu")
        self.drop = tf.keras.layers.Dropout(0.3)
        self.layer_list = [self.l1, self.drop, self.l2, self.drop, self.l3]

    def call(self, inputs, *args, training=None, **kwargs):
        x = self.l1(inputs)
        x = self.drop(x, training)
        x = self.l2(x)
        x = self.drop(x, training)
        return self.l3(x)


def _load_encoder_model(model_path: Path):
    ae_model = tf.keras.models.load_model(
        model_path,
        custom_objects={
            "AutoEncoder": AutoEncoder,
            "Encoder": Encoder,
            "Decoder": Decoder,
        },
    )
    encoder = ae_model.layers[3].encoder
    return encoder.sequential()


def _add_classification_layers(
    model: tf.keras.Sequential,
    n_classes=2,
    encoder_lr=0.001,
    classifier_lr=0.1,
    freeze_encoder_layers=False,
    dropout=0.3,
):
    if freeze_encoder_layers:
        for layer in model.layers[:]:
            layer.trainable = False

    optimizer = tf.keras.optimizers.Adam(learning_rate=encoder_lr)

    layers_before = len(model.layers)

    model.add(tf.keras.layers.Dense(6, name="DenseCls1", activation="sigmoid"))
    model.add(tf.keras.layers.Dropout(dropout, name="DropoutCls1"))
    model.add(
        tf.keras.layers.Dense(
            n_classes if n_classes != 2 else 1, name="DenseCls3", activation="sigmoid"
        )
    )

    classifier_layers = len(model.layers) - layers_before

    model.compile(optimizer=optimizer, loss="bce" if n_classes == 2 else "cce")

    return model
