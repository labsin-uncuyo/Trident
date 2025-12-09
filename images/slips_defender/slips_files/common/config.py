# SPDX-FileCopyrightText: 2021 Sebastian Garcia <sebastian.garcia@agents.fel.cvut.cz>
#  SPDX-License-Identifier: GPL-2.0-only
from enum import Enum
from functools import reduce
from typing import Optional

import pandas as pd
from pyhocon import ConfigFactory, ConfigTree, HOCONConverter
from pathlib import Path

from pyhocon.config_tree import NonExistentKey


class Setting(Enum):
    FEDERATED = "federated"
    CENTRALIZED = "centralized"
    LOCAL = "local"


class Config(ConfigTree):
    @staticmethod
    def load(config_path=None, **overrides):
        config_paths = [Path("default.conf")] + (
            [Path(config_path)] if config_path else []
        )
        config = Config._parse_files(config_paths)
        for key, value in overrides.items():
            config.put(key, value)
        config.__class__ = Config
        config.__init__()
        return config

    def save(self, file):
        file.write(HOCONConverter.to_hocon(self))

    @property
    def data_dir(self) -> Path:
        return Path(self["data_dir"])

    @property
    def malware_dir(self):
        return self.data_dir / "Processed" / "Malware"

    @property
    def experiment_dir(self) -> Path:
        directory = Path(f"{self.output_dir}/experiment_{self.id}")
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def model_dir(self) -> Path:
        directory = Path(self.experiment_dir / "model")
        if self.run_id is not None:
            directory = directory / f"{self.run_id:02}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def results_dir(self) -> Path:
        directory = self.experiment_dir / "results"
        if self.run_id is not None:
            directory = directory / f"{self.run_id:02}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def setting(self) -> Setting:
        return Setting(self["setting"])

    def results_file(self, day: int) -> Path:
        return (
            self.results_dir / f"day{day}_{self.seed}_{self.setting.value}_results.pckl"
        )

    def model_file(self, day: int, client_id=None) -> Path:
        if client_id is not None:
            return (
                self.model_dir
                / f"day{day}_{self.seed}_{self.setting.value}_{client_id}_model.h5"
            )
        return self.model_dir / f"day{day}_{self.seed}_{self.setting.value}_model.h5"

    def local_model_file(self, day: int, client_id: int) -> Path:
        return (
            self.model_dir
            / f"day{day}_{self.seed}_{self.setting.value}_{client_id}_model.h5"
        )

    def scaler_file(self, day: int) -> Path:
        return self.model_dir / f"day{day}_{self.seed}_{self.setting.value}_scaler.pckl"

    def local_epochs(self, rnd: int) -> int:
        epoch_config = {
            int(key): value for key, value in dict(self.server.local_epochs).items()
        }
        return epoch_config.get(rnd, epoch_config[-1])

    def client_malware(self, client_id: int, day: int) -> Optional[Path]:
        malware = {int(key): value for key, value in self.client.client_malware.items()}
        if client_id not in malware or malware[client_id][day - 1][0] == "_":
            return None

        malware = malware[client_id][day - 1]
        if "_" in malware:
            malware_id, malware_day = malware.split("_")
        else:
            malware_id, malware_day = malware, day
        return self.malware_dir / self.malware_dirs[malware_id] / f"Day{malware_day}"

    def vaccine(self, day: int) -> Optional[Path]:
        if "vaccine_malware" not in self.server:
            return None
        malware_name = self.server.vaccine_malware[day - 1]
        if malware_name == "_":
            return None
        malware_id, malware_day = malware_name.split("_")
        return self.malware_dir / self.malware_dirs[malware_id] / f"Day{malware_day}"

    @staticmethod
    def _parse_files(files):
        configs = []
        for file in files:
            configs.append(ConfigFactory.parse_file(file))

        config = configs[0]
        for other_config in configs[1:]:
            ConfigTree.merge_configs(config, other_config)
        return config

    def __getattr__(self, item):
        val = self.get(item, NonExistentKey)
        if val is NonExistentKey:
            return super(Config, self).__getattr__(item)
        return val
