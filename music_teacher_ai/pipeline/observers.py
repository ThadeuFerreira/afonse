from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Protocol


class ProgressHandle(Protocol):
    def update(self, *, advance: int, new: int, dup: int, req: int, variants: int) -> None: ...


class PipelineObserver(Protocol):
    def info(self, message: str) -> None: ...

    def debug(self, message: str) -> None: ...

    def warn(self, message: str) -> None: ...

    @contextmanager
    def progress(self, *, total: int, variants: int) -> Iterator[ProgressHandle]: ...


@dataclass
class _NoopProgress:
    def update(self, *, advance: int, new: int, dup: int, req: int, variants: int) -> None:
        return


class NullObserver:
    def info(self, message: str) -> None:
        return

    def debug(self, message: str) -> None:
        return

    def warn(self, message: str) -> None:
        return

    @contextmanager
    def progress(self, *, total: int, variants: int) -> Iterator[ProgressHandle]:
        yield _NoopProgress()


class RichObserver:
    def __init__(self) -> None:
        from rich.console import Console

        self._console = Console()

    def info(self, message: str) -> None:
        self._console.print(message)

    def debug(self, message: str) -> None:
        self._console.log(message)

    def warn(self, message: str) -> None:
        self._console.print(message)

    @contextmanager
    def progress(self, *, total: int, variants: int) -> Iterator[ProgressHandle]:
        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeElapsedColumn,
        )

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TextColumn(
                "[green]✓{task.fields[new]}[/green]  "
                "[dim]dup={task.fields[dup]}  "
                "req={task.fields[req]}  "
                "variants={task.fields[variants]}[/dim]"
            ),
            console=self._console,
            transient=False,
        )
        with progress:
            task = progress.add_task(
                "Enriching",
                total=total,
                new=0,
                dup=0,
                req=0,
                variants=variants,
            )

            @dataclass
            class _RichProgressHandle:
                _progress: Progress
                _task: int

                def update(
                    self, *, advance: int, new: int, dup: int, req: int, variants: int
                ) -> None:
                    self._progress.update(
                        self._task,
                        advance=advance,
                        new=new,
                        dup=dup,
                        req=req,
                        variants=variants,
                    )

            yield _RichProgressHandle(progress, task)
