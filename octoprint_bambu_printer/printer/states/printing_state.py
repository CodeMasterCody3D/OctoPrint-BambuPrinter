from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from octoprint_bambu_printer.printer.bambu_virtual_printer import (
        BambuVirtualPrinter,
    )

import threading

import octoprint_bambu_printer.printer.pybambu
import octoprint_bambu_printer.printer.pybambu.models
import octoprint_bambu_printer.printer.pybambu.commands

from octoprint_bambu_printer.printer.print_job import PrintJob
from octoprint_bambu_printer.printer.states.a_printer_state import APrinterState


class PrintingState(APrinterState):

    def __init__(self, printer: BambuVirtualPrinter) -> None:
        super().__init__(printer)
        self._printer.current_print_job = None
        self._is_printing = False
        self._sd_printing_thread = None

    def init(self):
        self._is_printing = True
        self._printer.remove_project_selection()
        self.update_print_job_info()
        self._start_worker_thread()

    def finalize(self):
        if self._sd_printing_thread is not None and self._sd_printing_thread.is_alive():
            self._is_printing = False
            self._sd_printing_thread.join()
            self._sd_printing_thread = None
        self._printer.current_print_job = None

    def _start_worker_thread(self):
        self._is_printing = True
        if self._sd_printing_thread is None:
            self._sd_printing_thread = threading.Thread(target=self._printing_worker)
            self._sd_printing_thread.start()
        else:
            self._sd_printing_thread.join()

    def _printing_worker(self):
        self._log.debug(f"_printing_worker before while loop: {self._printer.current_print_job}")
        while (
            self._is_printing
            and self._printer.current_print_job is not None
            and self._printer.current_print_job.progress < 100
        ):
            self.update_print_job_info()
            self._printer.report_print_job_status()
            time.sleep(3)

        self._log.debug(f"_printing_worker after while loop: {self._printer.current_print_job}")
        self.update_print_job_info()
        if (
            self._printer.current_print_job is not None
            and self._printer.current_print_job.progress >= 100
        ):
            self._printer.finalize_print_job()

    def update_print_job_info(self):
        print_job_info = self._printer.bambu_client.get_device().print_job
        subtask_name: str = print_job_info.subtask_name
        gcode_file: str = print_job_info.gcode_file

        self._log.debug(f"update_print_job_info: {print_job_info}")

        project_file_info = self._printer.project_files.get_file_by_name(subtask_name) or self._printer.project_files.get_file_by_name(gcode_file)
        if project_file_info is None:
            self._log.debug(f"No 3mf file found for {print_job_info}")
            self._printer.current_print_job = None
            self._printer.change_state(self._printer._state_idle)
            return

        progress = print_job_info.print_percentage
        if print_job_info.gcode_state == "PREPARE" and progress == 100:
            progress = 0
        self._printer.current_print_job = PrintJob(project_file_info, progress, print_job_info.remaining_time, print_job_info.current_layer, print_job_info.total_layers)
        self._printer.select_project_file(project_file_info.path.as_posix())

    def pause_print(self):
        if self._printer.bambu_client.connected:
            if self._printer.bambu_client.publish(octoprint_bambu_printer.printer.pybambu.commands.PAUSE):
                self._log.info("print paused")
            else:
                self._log.info("print pause failed")

    def cancel_print(self):
        if self._printer.bambu_client.connected:
            if self._printer.bambu_client.publish(octoprint_bambu_printer.printer.pybambu.commands.STOP):
                self._log.info("print cancelled")
                self._printer.finalize_print_job()
            else:
                self._log.info("print cancel failed")
