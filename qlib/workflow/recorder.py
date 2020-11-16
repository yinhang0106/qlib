# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import mlflow
import shutil, os, pickle, tempfile, codecs, datetime
from pathlib import Path
from ..utils.objm import FileManager
from ..log import get_module_logger

logger = get_module_logger("workflow", "INFO")


class Recorder:
    """
    This is the `Recorder` class for logging the experiments. The API is designed similar to mlflow.
    (The link: https://mlflow.org/docs/latest/python_api/mlflow.html)

    The status of the recorder can be SCHEDULED, RUNNING, FINISHED, FAILED.
    """

    # status type
    STATUS_S = "SCHEDULED"
    STATUS_R = "RUNNING"
    STATUS_FI = "FINISHED"
    STATUS_FA = "FAILED"

    def __init__(self, name, experiment_id):
        self.id = None
        self.name = name
        self.experiment_id = experiment_id
        self.start_time = None
        self.end_time = None
        self.status = Recorder.STATUS_S

    def __repr__(self):
        return str(self.info)

    def __str__(self):
        return str(self.info)

    @property
    def info(self):
        output = dict()
        output["class"] = "Recorder"
        output["id"] = self.id
        output["name"] = self.name
        output["experiment_id"] = self.experiment_id
        output["start_time"] = self.start_time
        output["end_time"] = self.end_time
        output["status"] = self.status
        return output

    def set_recorder_name(self, rname):
        self.recorder_name = rname

    def save_objects(self, local_path=None, artifact_path=None, **kwargs):
        """
        Save objects such as prediction file or model checkpoints to the artifact URI. User
        can save object through keywords arguments (name:value).

        Parameters
        ----------
        local_path : str
            if provided, them save the file or directory to the artifact URI.
        artifact_path=None : str
            the relative path for the artifact to be stored in the URI.
        """
        raise NotImplementedError(f"Please implement the `save_objects` method.")

    def load_object(self, name):
        """
        Load objects such as prediction file or model checkpoints.

        Parameters
        ----------
        name : str
            name of the file to be loaded.

        Returns
        -------
        The saved object.
        """
        raise NotImplementedError(f"Please implement the `load_object` method.")

    def start_run(self):
        """
        Start running or resuming the Recorder. The return value can be used as a context manager within a `with` block;
        otherwise, you must call end_run() to terminate the current run. (See `ActiveRun` class in mlflow)

        Returns
        -------
        An active running object (e.g. mlflow.ActiveRun object).
        """
        raise NotImplementedError(f"Please implement the `start_run` method.")

    def end_run(self):
        """
        End an active Recorder.
        """
        raise NotImplementedError(f"Please implement the `end_run` method.")

    def log_params(self, **kwargs):
        """
        Log a batch of params for the current run.

        Parameters
        ----------
        keyword arguments
            key, value pair to be logged as parameters.
        """
        raise NotImplementedError(f"Please implement the `log_params` method.")

    def log_metrics(self, step=None, **kwargs):
        """
        Log multiple metrics for the current run.

        Parameters
        ----------
        keyword arguments
            key, value pair to be logged as metrics.
        """
        raise NotImplementedError(f"Please implement the `log_metrics` method.")

    def set_tags(self, **kwargs):
        """
        Log a batch of tags for the current run.

        Parameters
        ----------
        keyword arguments
            key, value pair to be logged as tags.
        """
        raise NotImplementedError(f"Please implement the `set_tags` method.")

    def delete_tags(self, *keys):
        """
        Delete some tags from a run.

        Parameters
        ----------
        keys : series of strs of the keys
            all the name of the tag to be deleted.
        """
        raise NotImplementedError(f"Please implement the `delete_tags` method.")

    def list_artifacts(self, artifact_path: str = None):
        """
        List all the artifacts of a recorder.

        Parameters
        ----------
        artifact_path : str
            the relative path for the artifact to be stored in the URI.

        Returns
        -------
        A list of artifacts information (name, path, etc.) that being stored.
        """
        raise NotImplementedError(f"Please implement the `list_artifacts` method.")


class MLflowRecorder(Recorder):
    """
    Use mlflow to implement a Recorder.

    Due to the fact that mlflow will only log artifact from a file or directory, we decide to
    use file manager to help maintain the objects in the project.
    """

    def __init__(self, name, experiment_id, uri):
        super(MLflowRecorder, self).__init__(name, experiment_id)
        self._uri = uri
        self.artifact_uri = None
        # set up file manager for saving objects
        self.temp_dir = tempfile.mkdtemp()
        self.fm = FileManager(Path(self.temp_dir).absolute())
        self.client = mlflow.tracking.MlflowClient(tracking_uri=self._uri)

    def start_run(self):
        # start the run
        run = mlflow.start_run(self.id, self.experiment_id, self.name)
        # save the run id and artifact_uri
        self.id = run.info.run_id
        self.artifact_uri = run.info.artifact_uri
        self.start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.status = Recorder.STATUS_R
        logger.info(f"Recorder {self.id} starts running under Experiment {self.experiment_id} ...")

        return run

    def end_run(self, status: str = Recorder.STATUS_S):
        assert status in [
            Recorder.STATUS_S,
            Recorder.STATUS_R,
            Recorder.STATUS_FI,
            Recorder.STATUS_FA,
        ], f"The status type {status} is not supported."
        mlflow.end_run(status)
        self.end_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.status != Recorder.STATUS_S:
            self.status = status
        shutil.rmtree(self.temp_dir)

    def save_objects(self, local_path=None, artifact_path=None, **kwargs):
        assert self._uri is not None, "Please start the experiment and recorder first before using recorder directly."
        if local_path is not None:
            self.client.log_artifacts(self.id, local_path, artifact_path)
        else:
            for name, data in kwargs.items():
                self.fm.save_obj(data, name)
                self.client.log_artifact(self.id, self.fm.path / name, artifact_path)

    def load_object(self, name):
        assert self._uri is not None, "Please start the experiment and recorder first before using recorder directly."
        path = self.client.download_artifacts(self.id, name)
        try:
            with Path(path).open("rb") as f:
                f.seek(0)
                return pickle.load(f)
        except:
            with codecs.open(path, mode="r", encoding="utf-8") as f:
                return f.read()

    def log_params(self, **kwargs):
        keys = list(kwargs.keys())
        for name, data in kwargs.items():
            self.client.log_param(self.id, name, data)

    def log_metrics(self, step=None, **kwargs):
        keys = list(kwargs.keys())
        for name, data in kwargs.items():
            self.client.log_metric(self.id, name, data)

    def set_tags(self, **kwargs):
        keys = list(kwargs.keys())
        for name, data in kwargs.items():
            self.client.set_tag(self.id, name, data)

    def delete_tags(self, *keys):
        for count, key in enumerate(keys):
            self.client.delete_tag(self.id, key)

    def get_artifact_uri(self):
        if self.artifact_uri is not None:
            return self.artifact_uri
        else:
            raise Exception(
                "Please make sure the recorder has been created and started properly before getting artifact uri."
            )

    def list_artifacts(self, artifact_path=None):
        assert self._uri is not None, "Please start the experiment and recorder first before using recorder directly."
        artifacts = self.client.list_artifacts(self.id, artifact_path)
        return artifacts
