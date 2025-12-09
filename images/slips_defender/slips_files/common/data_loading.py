# SPDX-FileCopyrightText: 2021 Sebastian Garcia <sebastian.garcia@agents.fel.cvut.cz>
#  SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.utils import shuffle
from collections import defaultdict
import numpy as np

from common.config import Config

_label_cols = ["label", "detailedlabel"]
_id_cols = ["id.orig_h", "id.resp_h", "id.resp_p", "proto", "day", "hour"]


def load_ben_data(
    day: int, client_id: int, data_dir: Path, drop_labels=True, drop_four_tuple=True
):
    client_dir = data_dir / "Processed" / f"Client{client_id}"

    df_ben = _load_data(
        client_dir / f"Day{day}", drop_labels, drop_four_tuple, drop_malicious=True
    )
    df_ben_test = (
        _load_data(
            client_dir / f"Day{day + 1}",
            drop_labels,
            drop_four_tuple,
            drop_malicious=True,
        )
        if day < 5
        else pd.DataFrame(columns=df_ben.columns)
    )

    return df_ben, df_ben_test


def load_mal_data(day: int, data_dir: Path, drop_labels=True, drop_four_tuple=True):
    mal_data = defaultdict(pd.DataFrame)
    mal_dir = data_dir / "Processed" / "Malware"
    for folder in mal_dir.iterdir():
        mal_data[folder.name] = _load_data(
            folder / f"Day{day}", drop_labels, drop_four_tuple
        )

    return mal_data


def load_day_dataset(dataset_dir: Path, drop_labels=True, drop_four_tuple=True):
    if dataset_dir is not None:
        return _load_data(dataset_dir, drop_labels, drop_four_tuple)
    else:
        return pd.DataFrame()


def create_supervised_dataset(
    df_ben: pd.DataFrame,
    df_mal: pd.DataFrame,
    test_ratio=0.2,
    seed=None,
    resize_mal=False,
):
    if resize_mal and df_mal.size > 0:
        resized_array = np.resize(df_mal.to_numpy(), (df_ben.shape[0], df_mal.shape[1]))
        df_mal = pd.DataFrame(resized_array, columns=df_mal.columns)

    df = pd.concat((df_ben, df_mal), axis=0)

    y = (df.label == "Malicious").astype("double").to_numpy().astype("float32")
    X = df.drop(_label_cols, axis=1).to_numpy().astype("float32")

    if not test_ratio:
        X, y = shuffle(X, y, random_state=seed)
        return X, None, y, None
    else:
        return train_test_split(
            X, y, test_size=test_ratio, shuffle=True, random_state=seed
        )


def load_centralized_data(day: int, config: Config, train_malicious=True):
    if "num_fit_clients" in config:
        num_fit_clients = config.num_fit_clients
    else:
        num_fit_clients = 10 if config.fit_if_no_malware else 6
    ben_train, mal_train = zip(
        *[
            load_client_dataset(day, client, config)
            for client in range(1, num_fit_clients + 1)
        ]
    )

    ben_test, mal_test = zip(
        *[
            load_client_dataset(day, client, config)
            for client in range(1, config.num_evaluate_clients + 1)
        ]
    )

    if vaccine := config.vaccine(day):
        train_vaccine = _load_data(vaccine, drop_labels=False, drop_four_tuple=True)
        test_vaccine = _load_data(vaccine, drop_labels=False, drop_four_tuple=True)

        mal_train += (train_vaccine,)
        mal_test += (test_vaccine,)

    X_ben_train = pd.concat(ben_train, axis=0)
    X_mal_train = pd.concat(mal_train, axis=0) if train_malicious else pd.DataFrame()

    X_ben_test = pd.concat(ben_test, axis=0)
    X_mal_test = pd.concat(mal_test, axis=0)

    X_train, X_val, y_train, y_val = create_supervised_dataset(
        X_ben_train, X_mal_train, config.client.val_ratio, config.seed
    )

    X_test, _, y_test, _ = create_supervised_dataset(
        X_ben_test, X_mal_test, 0.0, config.seed
    )

    return X_train, X_val, X_test, y_train, y_val, y_test


def load_local_data(day: int, client_id: int, config: Config):
    X_ben_train, X_mal_train = load_client_dataset(day, client_id, config)

    X_train, X_val, y_train, y_val = create_supervised_dataset(
        X_ben_train, X_mal_train, config.client.val_ratio, config.seed
    )

    X_ben_test, X_mal_test = load_client_dataset(day, client_id, config)
    X_test, _, y_test, _ = create_supervised_dataset(
        X_ben_test, X_mal_test, 0.0, config.seed
    )

    return X_train, X_val, X_test, y_train, y_val, y_test


def load_client_dataset(day: int, client_id: int, config: Config):
    client_dir = config.data_dir / "Processed" / f"Client{client_id}"
    mal_dir = config.client_malware(client_id, day)

    df_ben = _load_data(
        client_dir / f"Day{day}",
        drop_labels=False,
        drop_four_tuple=True,
        drop_malicious=True,
    )
    df_mal = (
        _load_data(
            mal_dir, drop_labels=False, drop_four_tuple=True, drop_malicious=False
        )
        if mal_dir
        else pd.DataFrame()
    )

    return df_ben, df_mal


def load_all_data(
    day: int, data_dir: Path, drop_labels=True, drop_four_tuple=True, seed=None
):
    ben_train, ben_test = zip(
        *[
            load_ben_data(
                day,
                client,
                data_dir,
                drop_labels=False,
                drop_four_tuple=drop_four_tuple,
            )
            for client in range(1, 11)
        ]
    )
    X_ben_train = pd.concat(ben_train, axis=0)
    X_ben_test = pd.concat(ben_test, axis=0)

    X_mal_train = pd.concat(
        load_mal_data(
            day, data_dir, drop_labels=False, drop_four_tuple=drop_four_tuple
        ).values(),
        axis=0,
    )
    X_mal_test = pd.concat(
        load_mal_data(
            day + 1, data_dir, drop_labels=False, drop_four_tuple=drop_four_tuple
        ).values(),
        axis=0,
    )

    X_train, X_val, y_train, y_val = create_supervised_dataset(
        X_ben_train, X_mal_train, 0.2, seed
    )
    X_test, _, y_test, _ = create_supervised_dataset(X_ben_test, X_mal_test, 0.0, seed)

    return X_train, X_val, X_test, y_train, y_val, y_test


def _load_data(data_dir: Path, drop_labels, drop_four_tuple, drop_malicious=False):
    features_file = data_dir / "comb_features.csv"
    if not features_file.exists():
        return pd.DataFrame()
    df = pd.read_csv(features_file)

    dropped_cols = [
        "ssl_ratio",
        "self_signed_ratio",
        "SNI_equal_DstIP",
        "ratio_certificate_path_error",
        "ratio_missing_cert_in_cert_path",
    ]
    if drop_labels:
        dropped_cols += _label_cols
    if drop_four_tuple:
        dropped_cols += _id_cols

    if drop_malicious:
        df = df[df.label == "Benign"]

    return df.drop(dropped_cols, axis=1).drop_duplicates()
