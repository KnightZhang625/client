"""
test_wandb
----------------------------------

Tests for the `wandb.apis.PublicApi` module.
"""

import os
import json
import pytest
import platform
import requests

import wandb
from wandb import Api
from tests import utils


@pytest.fixture
def api(runner):
    return Api()


def test_api_auto_login_no_tty(mocker):
    with pytest.raises(wandb.UsageError):
        Api()


def test_base_url_sanitization(runner):
    api = Api({"base_url": "https://wandb.corp.net///"})
    assert api.settings["base_url"] == "https://wandb.corp.net"


def test_parse_project_path(api):
    e, p = api._parse_project_path("user/proj")
    assert e == "user"
    assert p == "proj"


def test_parse_project_path_proj(api, mock_server):
    e, p = api._parse_project_path("proj")
    assert e == "mock_server_entity"
    assert p == "proj"


def test_parse_path_simple(api):
    u, p, r = api._parse_path("user/proj/run")
    assert u == "user"
    assert p == "proj"
    assert r == "run"


def test_parse_path_leading(api):
    u, p, r = api._parse_path("/user/proj/run")
    assert u == "user"
    assert p == "proj"
    assert r == "run"


def test_parse_path_docker(api):
    u, p, r = api._parse_path("user/proj:run")
    assert u == "user"
    assert p == "proj"
    assert r == "run"


def test_parse_path_docker_proj(mock_server, api):
    u, p, r = api._parse_path("proj:run")
    assert u == "mock_server_entity"
    assert p == "proj"
    assert r == "run"


def test_parse_path_url(api):
    u, p, r = api._parse_path("user/proj/runs/run")
    assert u == "user"
    assert p == "proj"
    assert r == "run"


def test_parse_path_user_proj(mock_server, api):
    u, p, r = api._parse_path("proj/run")
    assert u == "mock_server_entity"
    assert p == "proj"
    assert r == "run"


def test_parse_path_proj(mock_server, api):
    u, p, r = api._parse_path("proj")
    assert u == "mock_server_entity"
    assert p == "proj"
    assert r == "proj"


def test_from_path(mock_server, api):
    project = api.from_path("test")
    assert isinstance(project, wandb.apis.public.Project)
    project = api.from_path("test/test")
    assert isinstance(project, wandb.apis.public.Project)
    run = api.from_path("test/test/test")
    assert isinstance(run, wandb.apis.public.Run)
    run = api.from_path("test/test/runs/test")
    assert isinstance(run, wandb.apis.public.Run)
    sweep = api.from_path("test/test/sweeps/test")
    assert isinstance(sweep, wandb.apis.public.Sweep)
    report = api.from_path("test/test/reports/XXX")
    assert isinstance(report, wandb.apis.public.BetaReport)
    report = api.from_path("test/test/reports/Name-foo--XXX")
    assert isinstance(report, wandb.apis.public.BetaReport)
    with pytest.raises(wandb.Error):
        api.from_path("test/test/barf/test")
    with pytest.raises(wandb.Error):
        api.from_path("test/test/test/test/test")
    with pytest.raises(wandb.Error):
        api.from_path("test/test/reports/test-foo")


def test_to_html(mock_server, api):
    project = api.from_path("test")
    assert "mock_server_entity/test/workspace?jupyter=true" in project.to_html()
    run = api.from_path("test/test/test")
    assert "test/test/runs/test?jupyter=true" in run.to_html()
    sweep = api.from_path("test/test/sweeps/test")
    assert "test/test/sweeps/test?jupyter=true" in sweep.to_html()
    report = api.from_path("test/test/reports/My-Report--XXX")
    report_html = report.to_html(hidden=True)
    assert "test/test/reports/My-Report--XXX" in report_html
    assert "<button" in report_html


def test_project_sweeps(mock_server, api):
    project = api.from_path("test")
    psweeps = project.sweeps()
    assert len(psweeps) == 1
    assert psweeps[0].id == "testid"
    assert psweeps[0].name == "testname"

    no_sweeps_project = api.from_path("testnosweeps")
    nspsweeps = no_sweeps_project.sweeps()
    assert len(nspsweeps) == 0


def test_display(mock_server, api):
    run = api.from_path("test/test/test")
    assert not run.display()


def test_run_load(mock_server, api):
    run = api.run("test/test/test")
    assert run.summary_metrics == {"acc": 100, "loss": 0}
    assert run.url == "https://wandb.ai/test/test/runs/test"


def test_run_from_tensorboard(runner, mock_server, api):
    with runner.isolated_filesystem():
        utils.fixture_copy("events.out.tfevents.1585769947.cvp")
        run_id = wandb.util.generate_id()
        api.sync_tensorboard(".", project="test", run_id=run_id)
        assert mock_server.ctx["graphql"][-1]["variables"] == {
            "entity": "mock_server_entity",
            "name": run_id,
            "project": "test",
        }


def test_run_retry(mock_server, api):
    mock_server.set_context("fail_graphql_times", 2)
    run = api.run("test/test/test")
    assert run.summary_metrics == {"acc": 100, "loss": 0}


def test_run_history(mock_server, api):
    run = api.run("test/test/test")
    assert run.history(pandas=False)[0] == {"acc": 10, "loss": 90}


def test_run_history_keys(mock_server, api):
    run = api.run("test/test/test")
    assert run.history(keys=["acc", "loss"], pandas=False) == [
        {"loss": 0, "acc": 100},
        {"loss": 1, "acc": 0},
    ]


def test_run_history_keys_bad_arg(mock_server, api, capsys):
    run = api.run("test/test/test")
    run.history(keys="acc", pandas=False)
    captured = capsys.readouterr()
    assert "wandb: ERROR keys must be specified in a list\n" in captured.err

    run.history(keys=[["acc"]], pandas=False)
    captured = capsys.readouterr()
    assert "wandb: ERROR keys argument must be a list of strings\n" in captured.err

    run.scan_history(keys="acc")
    captured = capsys.readouterr()
    assert "wandb: ERROR keys must be specified in a list\n" in captured.err

    run.scan_history(keys=[["acc"]])
    captured = capsys.readouterr()
    assert "wandb: ERROR keys argument must be a list of strings\n" in captured.err


def test_run_config(mock_server, api):
    run = api.run("test/test/test")
    assert run.config == {"epochs": 10}


def test_run_history_system(mock_server, api):
    run = api.run("test/test/test")
    assert run.history(stream="system", pandas=False) == [
        {"cpu": 10},
        {"cpu": 20},
        {"cpu": 30},
    ]


def test_run_summary(mock_server, api):
    run = api.run("test/test/test")
    run.summary.update({"cool": 1000})
    res = json.loads(mock_server.ctx["graphql"][-1]["variables"]["summaryMetrics"])
    assert {"acc": 100, "loss": 0, "cool": 1000} == res


def test_run_create(mock_server, api):
    run = api.create_run(project="test")
    variables = {"entity": "mock_server_entity", "name": run.id, "project": "test"}
    assert mock_server.ctx["graphql"][-1]["variables"] == variables


def test_run_update(mock_server, api):
    run = api.run("test/test/test")
    run.tags.append("test")
    run.config["foo"] = "bar"
    run.update()
    res = json.loads(mock_server.ctx["graphql"][-1]["variables"]["summaryMetrics"])
    assert {"acc": 100, "loss": 0} == res
    assert mock_server.ctx["graphql"][-2]["variables"]["entity"] == "test"


def test_run_delete(mock_server, api):
    run = api.run("test/test/test")

    run.delete()
    variables = {"id": run.storage_id, "deleteArtifacts": False}
    assert mock_server.ctx["graphql"][-1]["variables"] == variables

    run.delete(delete_artifacts=True)
    variables = {"id": run.storage_id, "deleteArtifacts": True}
    assert mock_server.ctx["graphql"][-1]["variables"] == variables


def test_run_files(runner, mock_server, api):
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        file = run.files()[0]
        file.download()
        assert os.path.exists("weights.h5")
        raised = False
        try:
            file.download()
        except wandb.CommError:
            raised = True
        assert raised


def test_run_file(runner, mock_server, api):
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        file = run.file("weights.h5")
        assert not os.path.exists("weights.h5")
        file.download()
        assert os.path.exists("weights.h5")


def test_run_file_direct(runner, mock_server, api):
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        file = run.file("weights.h5")
        assert (
            file.direct_url
            == "https://api.wandb.ai/storage?file=weights.h5&direct=true"
        )


def test_run_upload_file(runner, mock_server, api):
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        with open("new_file.pb", "w") as f:
            f.write("TEST")
        file = run.upload_file("new_file.pb")
        assert file.url == "https://api.wandb.ai/storage?file=new_file.pb"


def test_run_upload_file_relative(runner, mock_server, api):
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        wandb.util.mkdir_exists_ok("foo")
        os.chdir("foo")
        with open("new_file.pb", "w") as f:
            f.write("TEST")
        file = run.upload_file("new_file.pb", "../")
        assert file.url == "https://api.wandb.ai/storage?file=foo/new_file.pb"


def test_upload_file_retry(runner, mock_server, api):
    mock_server.set_context("fail_storage_count", 4)
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        with open("new_file.pb", "w") as f:
            f.write("TEST")
        file = run.upload_file("new_file.pb")
        assert file.url == "https://api.wandb.ai/storage?file=new_file.pb"


def test_runs_from_path(mock_server, api):
    runs = api.runs("test/test")
    assert len(runs) == 4
    list(runs)
    assert len(runs.objects) == 2
    assert runs[0].summary_metrics == {"acc": 100, "loss": 0}
    assert runs[0].group == "A"
    assert runs[0].job_type == "test"


def test_runs_from_path_index(mock_server, api):
    mock_server.set_context("page_times", 4)
    runs = api.runs("test/test")
    assert len(runs) == 4
    print(list(runs))
    assert runs[3]
    assert len(runs.objects) == 4


def test_projects(mock_server, api):
    projects = api.projects("test")
    # projects doesn't provide a length for now, so we iterate
    # them all to count
    count = 0
    for proj in projects:
        count += 1
    assert count == 2


def test_reports(mock_server, api):
    path = "test-entity/test-project"
    reports = api.reports(path)
    # calling __len__, __getitem__, or __next__ on a Reports object
    # triggers the actual API call to fetch data w/ pagination.
    length = len(reports)
    assert length == 1
    assert reports[0].description == "test-description"
    assert reports[0].pageCount == 0
    assert reports[1].pageCount == 1


def test_delete_file(runner, mock_server, api):
    run = api.run("test/test/test")
    file = run.files()[0]
    file.delete()

    assert mock_server.ctx["graphql"][-1]["variables"] == {"files": [file.id]}


def test_artifact_versions(runner, mock_server, api):
    versions = api.artifact_versions("dataset", "mnist")
    assert len(versions) == 2
    assert versions[0].name == "mnist:v0"
    assert versions[1].name == "mnist:v1"


def test_artifact_type(runner, mock_server, api):
    atype = api.artifact_type("dataset")
    assert atype.name == "dataset"
    col = atype.collection("mnist")
    assert col.name == "mnist"
    cols = atype.collections()
    assert cols[0].name == "mnist"


def test_artifact_types(runner, mock_server, api):
    atypes = api.artifact_types("dataset")

    raised = False
    try:
        assert len(atypes) == 2
    except ValueError:
        raised = True
    assert raised
    assert atypes[0].name == "dataset"


def test_artifact_get_path(runner, mock_server, api):
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    assert art.type == "dataset"
    assert art.name == "mnist:v0"
    with runner.isolated_filesystem():
        path = art.get_path("digits.h5")
        res = path.download()
        part = art.name
        if platform.system() == "Windows":
            part = "mnist-v0"
        path = os.path.join(".", "artifacts", part, "digits.h5")
        assert res == path


def test_artifact_get_path_download(runner, mock_server, api):
    with runner.isolated_filesystem():
        art = api.artifact("entity/project/mnist:v0", type="dataset")
        path = art.get_path("digits.h5").download(os.getcwd())
        assert os.path.exists("./digits.h5")
        assert path == os.path.join(os.getcwd(), "digits.h5")


def test_artifact_file(runner, mock_server, api):
    with runner.isolated_filesystem():
        art = api.artifact("entity/project/mnist:v0", type="dataset")
        path = art.file()
        if platform.system() == "Windows":
            part = "mnist-v0"
        else:
            part = "mnist:v0"
        assert path == os.path.join(".", "artifacts", part, "digits.h5")


def test_artifact_download(runner, mock_server, api):
    with runner.isolated_filesystem():
        art = api.artifact("entity/project/mnist:v0", type="dataset")
        path = art.download()
        if platform.system() == "Windows":
            part = "mnist-v0"
        else:
            part = "mnist:v0"
        assert path == os.path.join(".", "artifacts", part)
        assert os.listdir(path) == ["digits.h5"]


def test_artifact_delete(runner, mock_server, api):
    with runner.isolated_filesystem():
        art = api.artifact("entity/project/mnist:v0", type="dataset")

        # The artifact has aliases, so fail unless delete_aliases is set.
        with pytest.raises(Exception):
            art.delete()

        success = art.delete(delete_aliases=True)
        assert success


def test_artifact_checkout(runner, mock_server, api):
    with runner.isolated_filesystem():
        # Create a file that should be removed as part of checkout
        os.makedirs(os.path.join(".", "artifacts", "mnist"))
        with open(os.path.join(".", "artifacts", "mnist", "bogus"), "w") as f:
            f.write("delete me, i'm a bogus file")

        art = api.artifact("entity/project/mnist:v0", type="dataset")
        path = art.checkout()
        assert path == os.path.join(".", "artifacts", "mnist")
        assert os.listdir(path) == ["digits.h5"]


def test_artifact_run_used(runner, mock_server, api):
    run = api.run("test/test/test")
    arts = run.used_artifacts()
    assert len(arts) == 2
    assert arts[0].name == "mnist:v0"


def test_artifact_run_logged(runner, mock_server, api):
    run = api.run("test/test/test")
    arts = run.logged_artifacts()
    assert len(arts) == 2
    assert arts[0].name == "mnist:v0"


def test_artifact_run_logged_cursor(runner, mock_server, api):
    artifacts = api.run("test/test/test").logged_artifacts()
    count = 0
    for artifact in artifacts:
        count += 1

    assert len(artifacts) == count


def test_artifact_manual_use(runner, mock_server, api):
    run = api.run("test/test/test")
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    run.use_artifact(art)
    assert True


def test_artifact_bracket_accessor(runner, live_mock_server, api):
    art = api.artifact("entity/project/dummy:v0", type="dataset")
    assert art["t"].__class__ == wandb.Table
    assert art["s"] is None
    # TODO: Remove this once we support incremental adds
    with pytest.raises(ValueError):
        art["s"] = wandb.Table(data=[], columns=[])


def test_artifact_manual_log(runner, mock_server, api):
    run = api.run("test/test/test")
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    run.log_artifact(art)
    assert True


def test_artifact_manual_error(runner, mock_server, api):
    run = api.run("test/test/test")
    art = wandb.Artifact("test", type="dataset")
    with pytest.raises(wandb.CommError):
        run.log_artifact(art)
    with pytest.raises(wandb.CommError):
        run.use_artifact(art)
    with pytest.raises(wandb.CommError):
        run.use_artifact("entity/project/mnist:v0")
    with pytest.raises(wandb.CommError):
        run.log_artifact("entity/project/mnist:v0")


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Verify is broken on Windows"
)
def test_artifact_verify(runner, mock_server, api):
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    art.download()
    with pytest.raises(ValueError):
        art.verify()


def test_artifact_save_norun(runner, mock_server, test_settings):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "..", "assets", "2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
        artifact.add(wb_image, "my-image")
        artifact.save(settings=test_settings)


def test_artifact_save_run(runner, mock_server, test_settings):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "..", "assets", "2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
        artifact.add(wb_image, "my-image")
        run = wandb.init(settings=test_settings)
        artifact.save()
        run.finish()


def test_artifact_save_norun_nosettings(runner, mock_server, test_settings):
    test_folder = os.path.dirname(os.path.realpath(__file__))
    im_path = os.path.join(test_folder, "..", "assets", "2x2.png")
    with runner.isolated_filesystem():
        artifact = wandb.Artifact(type="dataset", name="my-arty")
        wb_image = wandb.Image(im_path, classes=[{"id": 0, "name": "person"}])
        artifact.add(wb_image, "my-image")
        artifact.save()


def test_sweep(runner, mock_server, api):
    sweep = api.sweep("test/test/test")
    assert sweep.entity == "test"
    assert sweep.best_run().name == "beast-bug-33"
    assert sweep.url == "https://wandb.ai/test/test/sweeps/test"


def test_run_wait_until_finished(runner, mock_server, api, capsys):
    run = api.run("test/test/test")
    run.wait_until_finished()
    out, _ = capsys.readouterr()
    status = mock_server.ctx["run_state"]
    assert f"Run finished with status: {status}" in out


def test_queued_job(runner, mock_server, api):
    queued_job = api.queued_job("test/test/test/test")
    queued_job.wait_until_running()
    assert queued_job._run_id == "test"


def test_query_team(mock_server, api):
    t = api.team("test")
    assert t.name == "test"
    assert t.members[0].account_type == "MEMBER"
    assert repr(t.members[0]) == "<Member test (MEMBER)>"


def test_viewer(mock_server, api):
    v = api.viewer
    assert v.admin is False
    assert v.username == "mock"
    assert v.api_keys == []
    assert v.teams == []


def test_create_service_account(mock_server, api):
    t = api.team("test")
    assert t.create_service_account("My service account").api_key == "Y" * 40
    mock_server.set_context("graphql_conflict", True)
    assert t.create_service_account("My service account") is None


def test_create_team(mock_server, api):
    t = api.create_team("test")
    assert t.name == "test"
    assert repr(t) == "<Team test>"


def test_create_team_exists(mock_server, api):
    mock_server.set_context("graphql_conflict", True)
    with pytest.raises(requests.exceptions.HTTPError):
        api.create_team("test")


def test_invite_user(mock_server, api):
    t = api.team("test")
    assert t.invite("test@test.com")
    assert t.invite("test")
    mock_server.set_context("graphql_conflict", True)
    assert t.invite("conflict") == False


def test_delete_member(mock_server, api):
    t = api.team("test")
    assert t.members[0].delete()
    mock_server.set_context("graphql_conflict", True)
    assert t.invite("conflict") == False


def test_query_user(mock_server, api):
    u = api.user("test@test.com")
    assert u.email == "test@test.com"
    assert u.api_keys == ["Y" * 40]
    assert u.teams == ["test"]
    assert repr(u) == "<User test@test.com>"


def test_query_user_multiple(mock_server, api):
    mock_server.set_context("num_search_users", 2)
    u = api.user("test@test.com")
    assert u.email == "test@test.com"
    users = api.users("test")
    assert len(users) == 2


def test_delete_api_key(mock_server, api):
    u = api.user("test@test.com")
    assert u.delete_api_key("Y" * 40)
    mock_server.set_context("graphql_conflict", True)
    assert u.delete_api_key("Y" * 40) == False


def test_generate_api_key(mock_server, api):
    u = api.user("test@test.com")
    assert u.generate_api_key()
    mock_server.set_context("graphql_conflict", True)
    assert u.generate_api_key() is None
