"""Module contains code for loading a DagFactory config and generating DAGs"""
import os
from typing import Any, Dict, Optional, Union, List

import yaml
from airflow.models import DAG

from dagfactory.dagbuilder import DagBuilder

# these are params that cannot be a dag name
SYSTEM_PARAMS: List[str] = ["default", "task_groups"]
ALLOWED_CONFIG_FILE_SUFFIX: List[str] = ["yaml", "yml"]


class DagFactory:
    """
    Takes a YAML config or a python dictionary and generates DAGs.

    :param config_filepath: the filepath of the DAG factory YAML config file.
        Must be absolute path to file. Cannot be used with `config`.
    :type config_filepath: str
    :param config: DAG factory config dictionary. Cannot be user with `config_filepath`.
    :type config: dict
    """

    def __init__(
        self, config_filepath: Optional[str] = None, config: Optional[dict] = None
    ) -> None:
        assert bool(config_filepath) ^ bool(
            config
        ), "Either `config_filepath` or `config` should be provided"
        if config_filepath:
            DagFactory._validate_config_filepath(config_filepath=config_filepath)
            self.config: Dict[str, Any] = DagFactory._load_config(
                config_filepath=config_filepath
            )
        if config:
            self.config: Dict[str, Any] = config

    @classmethod
    def from_directory(cls, config_dir):
        """
        Make instances of DagFactory for each yaml configuration files within a directory
        """
        cls._validate_config_filepath(config_dir)
        subs = os.listdir(config_dir)
        subs_fpath = [os.path.join(config_dir, sub) for sub in subs]

        for sub_fpath in subs_fpath:
            if os.path.isdir(sub_fpath):
                cls.from_directory(sub_fpath)
            elif os.path.isfile(sub_fpath) and sub_fpath.split('.')[-1] in ALLOWED_CONFIG_FILE_SUFFIX:
                dag_factory = cls(config_filepath=sub_fpath)
                dag_factory.clean_dags(globals())
                dag_factory.generate_dags(globals())

    @staticmethod
    def _validate_config_filepath(config_filepath: str) -> None:
        """
        Validates config file path is absolute
        """
        if not os.path.isabs(config_filepath):
            raise Exception("DAG Factory `config_filepath` must be absolute path")

    @staticmethod
    def _load_config(config_filepath: str) -> Dict[str, Any]:
        """
        Loads YAML config file to dictionary

        :returns: dict from YAML config file
        """
        # pylint: disable=consider-using-with
        try:
            config: Dict[str, Any] = yaml.load(
                stream=open(config_filepath, "r", encoding="utf-8"),
                Loader=yaml.FullLoader,
            )
        except Exception as err:
            raise Exception("Invalid DAG Factory config file") from err
        return config

    def get_dag_configs(self) -> Dict[str, Dict[str, Any]]:
        """
        Returns configuration for each the DAG in factory

        :returns: dict with configuration for dags
        """
        return {
            dag: self.config[dag]
            for dag in self.config.keys()
            if dag not in SYSTEM_PARAMS
        }

    def get_default_config(self) -> Dict[str, Any]:
        """
        Returns defaults for the DAG factory. If no defaults exist, returns empty dict.

        :returns: dict with default configuration
        """
        return self.config.get("default", {})

    def build_dags(self) -> Dict[str, DAG]:
        """Build DAGs using the config file."""
        dag_configs: Dict[str, Dict[str, Any]] = self.get_dag_configs()
        default_config: Dict[str, Any] = self.get_default_config()

        dags: Dict[str, Any] = {}

        for dag_name, dag_config in dag_configs.items():
            dag_config["task_groups"] = dag_config.get("task_groups", {})
            dag_builder: DagBuilder = DagBuilder(
                dag_name=dag_name,
                dag_config=dag_config,
                default_config=default_config,
            )
            try:
                dag: Dict[str, Union[str, DAG]] = dag_builder.build()
                dags[dag["dag_id"]]: DAG = dag["dag"]
            except Exception as err:
                raise Exception(
                    f"Failed to generate dag {dag_name}. verify config is correct"
                ) from err

        return dags

    # pylint: disable=redefined-builtin
    @staticmethod
    def register_dags(dags: Dict[str, DAG], globals: Dict[str, Any]) -> None:
        """Adds `dags` to `globals` so Airflow can discover them.

        :param: dags: Dict of DAGs to be registered.
        :param globals: The globals() from the file used to generate DAGs. The dag_id
            must be passed into globals() for Airflow to import
        """
        for dag_id, dag in dags.items():
            globals[dag_id]: DAG = dag

    def generate_dags(self, globals: Dict[str, Any]) -> None:
        """
        Generates DAGs from YAML config

        :param globals: The globals() from the file used to generate DAGs. The dag_id
            must be passed into globals() for Airflow to import
        """
        dags: Dict[str, Any] = self.build_dags()
        self.register_dags(dags, globals)

    def clean_dags(self, globals: Dict[str, Any]) -> None:
        """
        Clean old DAGs that are not on YAML config but were auto-generated through dag-factory

        :param globals: The globals() from the file used to generate DAGs. The dag_id
            must be passed into globals() for Airflow to import
        """
        dags: Dict[str, Any] = self.build_dags()

        # filter dags that exists in globals and is auto-generated by dag-factory
        dags_in_globals: Dict[str, Any] = {}
        for k, glb in globals.items():
            if isinstance(glb, DAG) and hasattr(glb, "is_dagfactory_auto_generated"):
                dags_in_globals[k] = glb

        # finding dags that doesn't exist anymore
        dags_to_remove: List[str] = list(set(dags_in_globals) - set(dags))

        # removing dags from DagBag
        for dag_to_remove in dags_to_remove:
            del globals[dag_to_remove]

    # pylint: enable=redefined-builtin
