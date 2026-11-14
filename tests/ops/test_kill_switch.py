import json

from muletrace.ops.kill_switch import run

ENVIRONMENT = {
    "KILL_FUNCTIONS": json.dumps({"scorer": 5, "copilot": 2}),
    "KILL_SCHEDULES": json.dumps([["default", "daily"], ["default", "weekly"]]),
}


class FakeLambda:
    def __init__(self) -> None:
        self.concurrency: dict[str, int] = {}

    def put_function_concurrency(self, **request: str | int) -> None:
        self.concurrency[str(request["FunctionName"])] = int(
            request["ReservedConcurrentExecutions"]
        )


class FakeScheduler:
    def __init__(self) -> None:
        self.schedules = {
            "daily": {
                "Name": "daily",
                "GroupName": "default",
                "Arn": "arn:read-only",
                "ScheduleExpression": "cron(0 6 * * ? *)",
                "FlexibleTimeWindow": {"Mode": "OFF"},
                "Target": {"Arn": "arn:target", "RoleArn": "arn:role"},
                "State": "ENABLED",
            },
            "weekly": {"Name": "weekly", "GroupName": "default", "State": "DISABLED"},
        }
        self.updates: list[dict[str, object]] = []

    def get_schedule(self, **request: str) -> dict[str, object]:
        assert request["GroupName"] == "default"
        return dict(self.schedules[request["Name"]])

    def update_schedule(self, **request: object) -> None:
        self.updates.append(request)
        self.schedules[str(request["Name"])]["State"] = str(request["State"])


def test_an_sns_event_throttles_functions_and_disables_enabled_schedules() -> None:
    lambdas, scheduler = FakeLambda(), FakeScheduler()
    sns_event = {"Records": [{"Sns": {"Message": "budget reached"}}]}
    result = run(sns_event, lambdas, scheduler, ENVIRONMENT)
    assert lambdas.concurrency == {"scorer": 0, "copilot": 0}
    assert result["schedules_disabled"] == ["daily"]
    update = scheduler.updates[0]
    assert update["State"] == "DISABLED"
    assert "Arn" not in update  # read-only fields are not sent back
    assert update["Target"] == {"Arn": "arn:target", "RoleArn": "arn:role"}
    assert run(sns_event, lambdas, scheduler, ENVIRONMENT)["schedules_disabled"] == []


def test_restore_puts_normal_concurrency_back_and_leaves_schedules_alone() -> None:
    lambdas, scheduler = FakeLambda(), FakeScheduler()
    run({}, lambdas, scheduler, ENVIRONMENT)
    result = run({"action": "restore"}, lambdas, scheduler, ENVIRONMENT)
    assert lambdas.concurrency == {"scorer": 5, "copilot": 2}
    assert result == {"action": "restore", "restored": {"copilot": 2, "scorer": 5}}
    assert scheduler.schedules["daily"]["State"] == "DISABLED"


def test_schedules_are_optional() -> None:
    lambdas = FakeLambda()
    result = run({}, lambdas, FakeScheduler(), {"KILL_FUNCTIONS": json.dumps({"scorer": 5})})
    assert result == {"action": "kill", "throttled": ["scorer"], "schedules_disabled": []}


def test_kill_switch_runs_on_the_plain_python_runtime() -> None:
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    code = (
        "import sys, muletrace.ops.kill_switch; "
        "heavy = {'lightgbm', 'numpy', 'polars', 'pydantic', 'yaml'} & set(sys.modules); "
        "print(sorted(heavy))"
    )
    output = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert output == "[]"
