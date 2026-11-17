"""Command line of the pipeline: ``python -m flotsilica <command>`` (RF25, AC32, AC33; plan, section 22). Adapted from project 04's ``cli.py``.

``run``, ``task`` and ``replay`` call ``pipeline.run_all``, ``pipeline.run_task`` and ``pipeline.replay``: the same task list, order and functions as the Airflow DAG, so the
whole flow runs on Windows without Airflow. ``figures`` calls ``figures.write_figures`` and ``docs-sync`` calls ``reporting.sync_block``: no step is written here.

Exit codes: 0 ok (also a run with no delivery left and a replay with nothing pending), 1 a task failed, 2 wrong usage or configuration (also a task refused by the state of
its run or because another writer holds the data folder), 3 the delivery or the source was rejected by the validation. A combination that cannot do what it says is refused
with 2 before anything is written: no option is ignored in silence (AC32). Every relative path of ``--config`` and of ``make-fixture`` is taken from ``$FLOTSILICA_HOME`` or
the project folder, never from the working directory (AC33). ``main(argv)`` is the entry the tests use, in the same process.

``serve`` (U19, plan section 18) runs the estimation API of the sealed model on ``127.0.0.1`` and nothing else: it has no task, writes nothing and, with a ``--host`` other than the
loopback address or a port out of range, exits with 2 before the configuration is read or the API imported. It exits with 2 too when there is no model to serve (no seal, another
configuration than the sealed one, an artifact that is not the registered one).

The top-level help imports only the configuration: the pipeline (scikit-learn) is imported by the commands that run tasks, and ``serve`` imports the API and the server only in its
own branch. A new command is a ``commands.add_parser`` in ``build_parser`` and a branch of ``_execute`` (``serve``, which runs no task, is a branch of ``main``).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from pathlib import Path

from flotsilica import texts
from flotsilica.config import DEFAULT_PROJECT_ROOT, ENV_CONFIG, ENV_HOME, LOOPBACK_HOST, load_config

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_REJECTED = 0, 1, 2, 3
SIGNALS = ("none", "sensor_signal", "lab_only")
TASK_COMMANDS = ("run", "task")          # the commands whose options name tasks: only they need the pipeline's list to build the parser
SUMMARY_MD = "evaluation_summary.md"
QUIET_KEYS = ("seconds", "sha256", "peak_working_set_mb", "peak_commit_mb", "memory_counter", "message")     # what a line of a task leaves out: it is in the state of the run


class _UsageError(ValueError):
    """A combination of options that cannot do what it says (before anything is written)."""


def _home() -> Path:
    home = os.environ.get(ENV_HOME)
    return Path(home).resolve() if home else DEFAULT_PROJECT_ROOT


def _common() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, metavar="RUTA",
                        help=f"archivo de configuración (por defecto ${ENV_CONFIG} o config/pipeline.toml); una ruta relativa se toma desde ${ENV_HOME} o la carpeta del proyecto")
    common.add_argument("-v", "--verbose", action="store_true", help="muestra el detalle de cada paso y la traza de la tarea que falla")
    return common


def build_parser(task_ids: tuple[str, ...] | None = None) -> argparse.ArgumentParser:
    """The parser. `task_ids` are the choices of ``--only``, ``--from`` and ``task`` (``pipeline.TASK_IDS``); without them those options take any name and the pipeline refuses
    an unknown one (the top-level help does not import the pipeline)."""
    parser = argparse.ArgumentParser(prog="python -m flotsilica", description="La sílice del concentrado de flotación, estimada con un rango antes de que llegue el laboratorio.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMANDO")
    common = _common()
    tasks = f" ({', '.join(task_ids)})" if task_ids else ""

    run = commands.add_parser("run", parents=[common], help="una corrida: la siguiente entrega, con las once tareas en orden", description=f"Una corrida con las tareas de pipeline.TASKS{tasks}.")
    run.add_argument("--only", nargs="+", choices=task_ids, metavar="TAREA", help="corre solo estas tareas de la corrida, en su orden")
    run.add_argument("--from", dest="start", choices=task_ids, metavar="TAREA", help="sigue la corrida desde esta tarea")
    run.add_argument("--run-key", metavar="CLAVE", help="la corrida que se continúa (con --only o --from)")

    replay = commands.add_parser("replay", parents=[common], help="corridas seguidas, una por entrega pendiente, hasta agotarlas o hasta una entrega")
    replay.add_argument("--until", metavar="ENTREGA", help="la última entrega que se corre, por su identificador (por ejemplo D2017-06-01T00; por defecto, todas las pendientes)")

    task = commands.add_parser("task", parents=[common], help="una tarea de una corrida", description=f"Una tarea de una corrida{tasks}.")
    task.add_argument("task", choices=task_ids, metavar="TAREA")
    task.add_argument("--run-key", metavar="CLAVE", help="la corrida a la que pertenece (una nueva si se omite)")

    fixture = commands.add_parser("make-fixture", help="escribe un archivo ARFF sintético para las pruebas y el modo rápido")
    fixture.add_argument("output", type=Path, metavar="SALIDA.arff", help="dónde se escribe; una ruta relativa se toma desde la carpeta del proyecto")
    fixture.add_argument("--rows-per-hour", type=int, default=12, help="filas por hora (por defecto 12; la configuración rápida espera 12)")
    fixture.add_argument("--seed", type=int, default=0, help="semilla de la simulación (por defecto 0)")
    fixture.add_argument("--signal", choices=SIGNALS, default="none",
                         help="sensor_signal: la sílice suma un término del flujo de amina (control positivo); lab_only: los sensores son ruido (control negativo)")
    fixture.add_argument("--weeks", type=int, help="corta el archivo a las primeras N semanas (por defecto, el calendario completo)")

    serve = commands.add_parser("serve", parents=[common], help=f"levanta la API local de estimación en {LOOPBACK_HOST} (GET /health y POST /estimate), de solo lectura",
                                description="Sirve el modelo sellado con FastAPI y uvicorn: GET /health dice qué modelo y qué configuración sirve y POST /estimate da las tres estimaciones de una hora "
                                            "con su rango, con la misma función que el flujo. No escribe nada y solo escucha en la interfaz local.")
    serve.add_argument("--host", default=LOOPBACK_HOST, metavar="DIRECCIÓN",
                       help=f"interfaz en la que escucha: solo {LOOPBACK_HOST} (por defecto); otra sale con 2 antes de cargar nada")
    serve.add_argument("--port", type=int, metavar="N", help="puerto, de 1 a 65535 (por defecto el [api] port de la configuración)")

    commands.add_parser("figures", parents=[common], help="dibuja las siete figuras de la documentación desde los archivos del sitio verificados de la última corrida")
    commands.add_parser("docs-sync", parents=[common], help=f"copia el resumen de resultados (reports/{SUMMARY_MD}) en el bloque de resultados del README")
    return parser


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


def _fail(text: str) -> None:
    sys.stderr.write(text + "\n")


class _LineFormatter(logging.Formatter):
    """One line per record: the traceback of a failed task is printed once, by ``main`` with ``-v``."""

    def formatException(self, ei) -> str:
        return ""


def _configure_logging(verbose: bool) -> None:
    """Log to the standard error from the package's own logger, one line per record, replacing the handler of an earlier call in this process (the tests make several):
    information with ``-v``, warnings and errors without it."""
    package = logging.getLogger("flotsilica")
    for handler in [h for h in package.handlers if getattr(h, "_flotsilica_cli", False)]:
        package.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler._flotsilica_cli = True   # type: ignore[attr-defined]
    handler.setFormatter(_LineFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    package.addHandler(handler)
    package.setLevel(logging.INFO if verbose else logging.WARNING)


def _check_run(args: argparse.Namespace, task_ids: tuple[str, ...]) -> None:
    """The combinations of ``run`` that cannot do what they say, refused before a state file is created (plan, section 22)."""
    if args.only and args.start is not None:
        raise _UsageError(texts.only_with_from())
    if args.run_key and not args.only and args.start is None:
        raise _UsageError(texts.run_key_needs_a_selection())
    first = next(t for t in task_ids if t in args.only) if args.only else (args.start or task_ids[0])
    if args.run_key is None and first != task_ids[0]:
        raise _UsageError(texts.a_new_run_starts_at(task_ids[0], first))


def _brief(result: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in result.items() if k not in QUIET_KEYS and v is not None and not isinstance(v, (dict, list)))


def _show_run(outcome: list[dict]) -> None:
    for step in outcome:
        result = step["result"]
        if step["task"] == "deliver" and result.get("delivered"):
            _say(f"entrega {result['delivery_id']} (cálculo al {result['as_of']})")
        _say(f"{step['task']:<18} {result.get('seconds', 0):>8.1f} s  {_brief(result)}")
    if outcome and not outcome[-1]["result"].get("delivered", True):
        _say(outcome[-1]["result"]["message"])


def _make_fixture(args: argparse.Namespace) -> int:
    root = DEFAULT_PROJECT_ROOT
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))   # the generator lives with the tests, next to src/
    try:
        from tests.fixtures.make_fixture import make_fixture
    except ModuleNotFoundError as error:
        if error.name not in ("tests", "tests.fixtures", "tests.fixtures.make_fixture"):
            raise   # a module the generator itself needs is missing: a real error, not an absent tests tree
        raise _UsageError(texts.fixture_without_tests_tree(root)) from error

    home = _home()
    output = args.output if args.output.is_absolute() else Path(os.path.normpath(home / args.output))   # like the paths of the configuration: never the working directory
    if not args.output.is_absolute() and home not in output.parents:
        raise _UsageError(texts.fixture_outside_the_project(args.output, home))
    missing = [folder for folder in reversed(output.parents) if not folder.exists()]    # a clean clone has no data/quick/ yet: the folders this call makes, which it takes back
    output.parent.mkdir(parents=True, exist_ok=True)                                    # if the generator refuses its arguments (nothing is left behind)
    try:
        truth = make_fixture(output, rows_per_hour=args.rows_per_hour, seed=args.seed, signal=args.signal, weeks=args.weeks)
    except BaseException:
        for folder in reversed(missing):
            try:
                folder.rmdir()
            except OSError:
                break
        raise
    _say(texts.fixture_written(truth.path, truth.n_rows, len(truth.hours), args.seed, args.signal))
    return EXIT_OK


def _docs_sync(cfg) -> int:
    from flotsilica.reporting import RESULTS_END, RESULTS_START, sync_block

    summary, readme = Path(cfg.paths.reports_dir) / SUMMARY_MD, Path(cfg.paths.readme)
    if not readme.is_file():   # the quick mode has no README of its own
        raise _UsageError(texts.docs_sync_without_readme(readme, summary))
    if not summary.is_file():
        raise _UsageError(texts.docs_sync_without_summary(summary))
    try:
        changed = sync_block(readme, RESULTS_START, RESULTS_END, summary.read_text(encoding="utf-8"))
    except ValueError as error:   # a README without its two markers, once each and in order: nothing was written
        raise _UsageError(f"{error}. {texts.NOTHING_WRITTEN}") from error
    _say(f"{readme.name} actualizado" if changed else f"{readme.name} ya estaba al día")
    return EXIT_OK


def _figures(cfg) -> int:
    from flotsilica.figures import write_figures   # matplotlib: only the command that draws pays for it

    try:
        paths = write_figures(cfg.paths.site_dir, cfg.paths.figures_dir)
    except FileNotFoundError as error:   # no site files, or a folder that is not one export (SiteSetError): nothing was written
        raise _UsageError(texts.figures_refused(error)) from error
    for path in paths:
        _say(f"escribí {path}")
    return EXIT_OK


def _execute(args: argparse.Namespace, cfg, pipeline) -> int:
    if args.command == "docs-sync":
        return _docs_sync(cfg)
    if args.command == "figures":
        return _figures(cfg)
    if args.command == "task":
        result = pipeline.run_task(args.task, args.run_key, cfg)
        _say(f"{args.task}: {_brief(result)}")
        return EXIT_OK
    if args.command == "replay":
        runs = pipeline.replay(cfg, args.until)
        for outcome in runs:
            _show_run(outcome)
        _say(texts.runs_count(len(runs)) if runs else texts.NO_PENDING_DELIVERIES)
        return EXIT_OK
    _show_run(pipeline.run_all(cfg, only=args.only, start=args.start, run_key=args.run_key))
    return EXIT_OK


def _serve(args: argparse.Namespace) -> int:
    """``serve``: the refusals that need nothing loaded first (the host and the port), then the configuration, then the app of the sealed model, then the server."""
    try:
        if args.host != LOOPBACK_HOST:
            raise _UsageError(texts.serve_host_refused(args.host, LOOPBACK_HOST))
        if args.port is not None and not 1 <= args.port <= 65535:
            raise _UsageError(texts.serve_port_refused(args.port))
        cfg = load_config(args.config)
    except (_UsageError, ValueError, FileNotFoundError) as error:
        _fail(f"error: {error}")
        return EXIT_USAGE
    from flotsilica.api import ApiStartError, create_app      # the API, its libraries and the model are loaded only here
    from flotsilica.registry import ArtifactError, SealError

    try:
        app = create_app(cfg)
    except (ApiStartError, ArtifactError, SealError) as error:   # there is no model to serve: nothing was written and no server was started
        _fail(f"error: {error}")
        return EXIT_USAGE
    except Exception as error:   # an artifact with the registered hash that is not a model, for one
        _fail(f"falló: {type(error).__name__}: {error}")
        if args.verbose:
            _fail("".join(traceback.format_exception(error)).rstrip())
        return EXIT_FAILED
    import uvicorn

    uvicorn.run(app, host=cfg.api.host, port=cfg.api.port if args.port is None else args.port, log_level="info" if args.verbose else "warning")
    return EXIT_OK


def _command_of(argv: list[str]) -> str | None:
    return next((a for a in argv if not a.startswith("-")), None)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    task_ids = None
    if _command_of(argv) in TASK_COMMANDS:
        from flotsilica.pipeline import TASK_IDS

        task_ids = TASK_IDS
    try:
        args = build_parser(task_ids).parse_args(argv)
    except SystemExit as stop:   # argparse exits on a wrong option (2) and on --help (0)
        return int(stop.code or 0)
    _configure_logging(getattr(args, "verbose", False))
    if args.command == "serve":
        return _serve(args)
    if args.command == "make-fixture":
        try:
            return _make_fixture(args)
        except (ValueError, OSError) as error:   # a count or a seed the generator refuses, or a path that cannot be written
            _fail(f"error: {error}")
            return EXIT_USAGE
    try:
        if args.command == "run":
            _check_run(args, task_ids)
        cfg = load_config(args.config)
    except (ValueError, FileNotFoundError) as error:   # a wrong option or configuration: nothing has been written
        _fail(f"error: {error}")
        return EXIT_USAGE
    from flotsilica import pipeline
    from flotsilica.validate import ValidationError

    try:
        return _execute(args, cfg, pipeline)
    except ValidationError as error:
        _fail(f"rechazada: {error}")
        return EXIT_REJECTED
    except (_UsageError, pipeline.UsageError, pipeline.RunRefusedError) as error:   # refused before anything ran or was written
        _fail(f"error: {error}")
        return getattr(error, "exit_code", EXIT_USAGE)
    except Exception as error:   # a task failed: its record is in the state of the run
        _fail(f"falló: {type(error).__name__}: {error}")
        if getattr(args, "verbose", False):
            _fail("".join(traceback.format_exception(error)).rstrip())
        return EXIT_FAILED


__all__ = ["EXIT_FAILED", "EXIT_OK", "EXIT_REJECTED", "EXIT_USAGE", "build_parser", "main"]
