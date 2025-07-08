from enum import Enum
from typing import Optional
import collections
import sys

import click

import client


TOOL_NAME = "GHARF"


class CliCommandType(Enum):
    SHELL = "shell"
    JAVASCRIPT = "javascript"
    UPLOAD_FILE = "upload-file"
    UPLOAD_RUN = "upload-run"
    DOWNLOAD_FILE = "download-file"
    DOWNLOAD_RUN = "download-run"
    DOWNLOAD_LIST = "download-list"
    CUSTOM_MODULE = "custom-module"
    LOGS = "logs"

    @classmethod
    def get_values(self) -> list:
        return [command.value for command in self]

    def __str__(self):
        return self.value


class InteractiveContext:
    """A class that manages the interactive shell state"""
    def __init__(self):
        self.prompt_suffix = "> "
        self.prompt_main = TOOL_NAME
        self.running = True
        self.current_mode = None
        self.target_hostlabel = None

    def get_prompt(self):
        if self.current_mode is None:
            prompt = f"{self.prompt_main}"
        else:
            prompt = f"{self.prompt_main}[{self.target_hostlabel}][{self.current_mode.value}]"

        return click.style(prompt, fg=(255, 20, 80))


def interactive_mode(current_mode=None):
    """The main loop for interactive mode"""
    ctx = InteractiveContext()
    if current_mode is not None:
        ctx.current_mode = current_mode
    click.echo("Type 'help' for commands or 'exit' to quit")
    
    while ctx.running:
        try:
            if ctx.current_mode is None:
                # Normal mode prompt
                user_input = click.prompt(ctx.get_prompt(), type=str, prompt_suffix=ctx.prompt_suffix)
                command_selection(user_input, ctx)
                
            else:
                # Subcommand mode prompt (enter parameters)
                execute_subcommand_interactive(ctx)
        except KeyboardInterrupt:
            click.echo("\nExiting...")
            break
        except Exception as e:
            click.echo(click.style(f"Error: {str(e)}", fg="red"), err=True)
            exception_type, exception_object, exception_traceback = sys.exc_info()
            click.echo(click.style(f"file: {exception_traceback.tb_frame.f_code.co_filename}", bg="red"), err=True)
            click.echo(click.style(f"line: {exception_traceback.tb_lineno}", bg="red"), err=True)
            click.echo("\nExiting...")
            break


def command_selection(user_input, ctx):
    """
    Command preprocessing
    Set command and host label information in the context (ctx)
    If an interactive command is specified, the mode will be switched in the loop of the calling shell
    """
    command, *args = user_input.strip().split()

    if command == "exit":
        ctx.running = False
        click.echo("Exiting...")
        return
    if command == "help":
        # sub command help
        if 0 < len(args):
            show_help(args[0])
        else:
            show_help()
        return
    if command == CliCommandType.DOWNLOAD_LIST.value:
        if args and args[0] == "--n":
            client.download_list(args=args, standalone_mode=False)
        elif args:
            client.download_list(args=["--n", *args], standalone_mode=False)
        else:
            client.download_list(standalone_mode=False)
        return
    if command == CliCommandType.LOGS.value:
        if args:
            client.logs(args=args, standalone_mode=False)
        else:
            client.logs(standalone_mode=False)
        return

    # If the command requires a host label and is not set, the host label must be selected
    hostlabel_required_list = ("shell", "javascript", "download-run", "custom-module")
    if command in hostlabel_required_list and ctx.target_hostlabel is None:
        click.echo("Select the target hostlabel by number from the following")
        cand_hostlabel_list = client.get_all_c2_hostlabels()
        for i, cand_hostlabel in enumerate(cand_hostlabel_list):
            click.echo(f"{i + 1}. {cand_hostlabel}")

        index = click.prompt("Enter the number", type=int)

        ctx.target_hostlabel = cand_hostlabel_list[index - 1]
        
        # Call again
        #command_selection(user_input, ctx)

    # Set command mode
    if command == CliCommandType.SHELL.value:
        ctx.current_mode = CliCommandType.SHELL
        click.echo("Enter shell command(inline, stateless)")
        click.echo("Type '!exit' to exit shell mode")
    elif command == CliCommandType.JAVASCRIPT.value:
        click.echo("Enter JavaScript code(inline, stateless)")
        click.echo("Type '!exit' to exit JavaScript mode")
        ctx.current_mode = CliCommandType.JAVASCRIPT
    elif command == CliCommandType.UPLOAD_FILE.value:
        ctx.current_mode = CliCommandType.UPLOAD_FILE
    elif command == CliCommandType.UPLOAD_RUN.value:
        ctx.current_mode = CliCommandType.UPLOAD_RUN
    elif command == CliCommandType.DOWNLOAD_FILE.value:
        ctx.current_mode = CliCommandType.DOWNLOAD_FILE
    elif command == CliCommandType.DOWNLOAD_RUN.value:
        ctx.current_mode = CliCommandType.DOWNLOAD_RUN
    elif command == CliCommandType.CUSTOM_MODULE.value:
        ctx.current_mode = CliCommandType.CUSTOM_MODULE
    elif command == CliCommandType.LOGS.value:
        ctx.current_mode = CliCommandType.LOGS
    else:
        if command:
            click.echo(f"Unknown command: {command}")
            click.echo("Type 'help' to see available commands")


def execute_subcommand_interactive(ctx):
    """Enter parameters for a subcommand interactively and execute it"""
    if ctx.current_mode == CliCommandType.SHELL:
        sourcecode = click.prompt(ctx.get_prompt(), type=str, prompt_suffix="$ ")
        if not sourcecode:
            return
        if sourcecode.strip() == "!exit":
            ctx.current_mode = None
            return

        execute_shell(sourcecode, ctx.target_hostlabel)
    
    elif ctx.current_mode == CliCommandType.JAVASCRIPT:
        sourcecode = click.prompt(ctx.get_prompt(), type=str, prompt_suffix="> ")
        if not sourcecode:
            return
        if sourcecode.strip() == "!exit":
            ctx.current_mode = None
            return
        
        execute_javascript(sourcecode, ctx.target_hostlabel)
        
    elif ctx.current_mode == CliCommandType.UPLOAD_RUN:
        answer = click.prompt("Do you want to upload files in the GitHub upload directory?[Y/n]", default="", show_default=False)
        ctx.current_mode = None
        # TODO: Implementation of Y/n needs to be considered
        if answer.lower().startswith("n"):
            click.echo("Cancelled")
            return
        result = execute_upload_run(ctx.target_hostlabel)
        if result != -1:
            click.echo("Upload job has started")
    
    elif ctx.current_mode == CliCommandType.UPLOAD_FILE:
        filepath = click.prompt("Enter filepath to upload to", type=str)
        ctx.current_mode = None
        result = execute_upload_file(filepath, ctx.target_hostlabel)
        if result != -1:
            click.echo("Upload job has started")
        
    elif ctx.current_mode == CliCommandType.DOWNLOAD_RUN:
        filepath = click.prompt("Enter filepath to download to", type=str)
        ctx.current_mode = None
        if not filepath:
            click.echo(click.style(f"Error: Filepath is required for download", fg="red"), err=True)
            return
        result = execute_download_run(filepath, ctx.target_hostlabel)
        if result != -1:
            click.echo("Download job has started")
    elif ctx.current_mode == CliCommandType.DOWNLOAD_FILE:
        job_id = click.prompt("Enter the job_id of the download job", type=str)
        ctx.current_mode = None
        if not job_id:
            click.echo(click.style(f"Error: job_id is required for download", fg="red"), err=True)
            return
        result = execute_download_file(job_id)
        if result != -1:
            click.echo("Download successful")
    elif ctx.current_mode == CliCommandType.CUSTOM_MODULE:
        ctx.current_mode = None
        avarable_custom_module_list = client.get_custom_modules()
        click.echo("Select the custom module by number or name from the following")
        for i, avarable_module_name in enumerate(avarable_custom_module_list):
            click.echo(f"{i + 1}. {avarable_module_name}")
        index_or_name = click.prompt("Enter the number or name", type=str)
        if index_or_name.isdigit() and int(index_or_name) <= len(avarable_module_name):
            index = int(index_or_name)
            module_name = avarable_custom_module_list[index]
        else:
            module_name = index_or_name
    
        execute_custom_module(module_name, ctx.target_hostlabel)


def show_help(command_name=None):
    with client.cli.make_context(info_name=TOOL_NAME, args=[]) as ctx:
        if command_name is None:
            all_help_text = ctx.get_help()
            command_help_text = all_help_text[all_help_text.index("Commands:"):]
        else:
            if command_name not in CliCommandType.get_values():
                click.echo(click.style(f'Error: command "{command_name}" not found', fg="red"), err=True)
                return -1
            command = client.cli.get_command(ctx, command_name)
            command_help_text = command.get_help(ctx)
            
    click.echo(command_help_text)


def execute_shell(sourcecode, hostlabel):
    click.echo(f"Executing shell command: {sourcecode}")
    args = ["--sourcecode", sourcecode, "--hostlabel", hostlabel]
    return client.shell(args, standalone_mode=False)


def execute_javascript(sourcecode, hostlabel):
    click.echo(f"Executing JavaScript: {sourcecode}")
    args = ["--sourcecode", sourcecode, "--hostlabel", hostlabel]
    return client.javascript(args, standalone_mode=False)


def execute_upload_file(filepath):
    click.echo(f"Uploading files")
    args = ["--filepath", filepath]
    return client.upload_file(args, standalone_mode=False)


def execute_upload_run(hostlabel):
    click.echo(f"Uploading files")
    args = ["--hostlabel", hostlabel]
    return client.upload_run(args, standalone_mode=False)


def execute_download_run(filepath, hostlabel):
    click.echo(f"Downloading to file: {filepath}")
    args = ["--filepath", filepath, "--hostlabel", hostlabel]
    return client.download_run(args, standalone_mode=False)


def execute_download_file(job_id):
    click.echo(f"Downloading files from job id {job_id}")
    args = ["--job-id", job_id]
    return client.download_file(args, standalone_mode=False)


def execute_custom_module(module_name, hostlabel):
    click.echo(f"Invoke the custom module: {module_name}")
    args = ["--module-name", module_name, "--hostlabel", hostlabel]
    return client.custom_module(args, standalone_mode=False)


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """Interactive CLI tool for executing various commands."""
    if ctx.invoked_subcommand is None:
        # Welcome message
        with open("assets/gharf-text-aa.txt", "r") as f:
            tool_name_aa = f.read()
        with open("assets/gharf-icon-aa.txt", "r") as f:
            icon_aa = f.readlines()
        
        merged_aa = "\n".join([icon_line[:-1] + "     " +  name_line for icon_line, name_line in zip(icon_aa, tool_name_aa.splitlines())])
        click.echo(rf"""Welcome to {TOOL_NAME.upper()}!
{merged_aa}""")
        # If no subcommand is specified, launches the base interactive mode
        interactive_mode()


@cli.command()
@click.argument("sourcecode", required=False)
@click.argument("hostlabel", required=False)
def shell(sourcecode, hostlabel):
    """Execute a shell command."""
    if sourcecode and hostlabel:    
        execute_shell(sourcecode, hostlabel)
    else:
        # If only a subcommand is specified, enters interactive mode
        interactive_mode(current_mode=CliCommandType.SHELL)


@cli.command()
@click.argument("sourcecode", required=False)
@click.argument("hostlabel", required=False)
def javascript(sourcecode, hostlabel):
    """Execute JavaScript code."""
    if sourcecode and hostlabel:
        execute_javascript(sourcecode, hostlabel)
    else:
        # If only a subcommand is specified, enters interactive mode
        interactive_mode(current_mode=CliCommandType.JAVASCRIPT)


@cli.command()
@click.argument("filepath", required=False)
def upload_file(filepath):
    """Upload files from local to GitHub repository."""
    # TODO: local path check
    if filepath:
        execute_upload_file(filepath)
    else:
        # If only a subcommand is specified, enters interactive mode
        interactive_mode(current_mode=CliCommandType.UPLOAD_FILE)


@cli.command()
@click.argument("hostlabel", required=False)
def upload_run(hostlabel):
    """Upload files from GitHub upload repository."""
    #execute_upload()
    # Always enter interactive mode (to skip to Y/n)
    interactive_mode(current_mode=CliCommandType.UPLOAD_RUN)


@cli.command()
@click.argument("filepath", required=False)
@click.argument("hostlabel", required=False)
def download_run(filepath, hostlabel):
    """Run a job to download files as artifacts from the runner to the repository."""
    if filepath:
        execute_download_run(filepath, hostlabel)
    else:
        # If only a subcommand is specified, enters interactive mode
        interactive_mode(current_mode=CliCommandType.DOWNLOAD_RUN)


@cli.command()
@click.argument("job_id", required=False)
@click.argument("hostlabel", required=False)
def download_file(job_id, hostlabel):
    """Run a job to download files as artifacts from the runner to the repository."""
    if job_id:
        execute_download_file(job_id, hostlabel)
    else:
        # If only a subcommand is specified, enters interactive mode
        interactive_mode(current_mode=CliCommandType.DOWNLOAD_FILE)


@cli.command()
@click.argument("hostlabel", required=False)
def custom_module(hostlabel):
    """Invoke a acustom module workflow."""
    #execute_custom_module(...)
    # Always enter interactive mode (to let you choose modules)
    interactive_mode(current_mode=CliCommandType.CUSTOM_MODULE)


if __name__ == "__main__":
    cli()
