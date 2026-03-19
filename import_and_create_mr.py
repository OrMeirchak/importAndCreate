import os
import shutil
import subprocess
import sys
import tarfile
import tempfileimport urllib.parse
import webbrowser
from pathlib import Path
from tkinter import Tk, filedialog, simpledialog, messagebox


# =======================================
# Script configuration
# =======================================

GIT_REMOTE_URL = "https://gitlab.com/mycompany-group2105712/mygit.git"
GITLAB_PROJECT_PATH = "mycompany-group2105712/mygit"

DEFAULT_SOURCE_BRANCH = "import-package"
DEFAULT_TARGET_BRANCH = "dev"

GIT_AUTHOR_NAME = "Auto Import Script"
GIT_AUTHOR_EMAIL = "auto-import@example.com"

PRESERVE_PATHS = [
    "FoldToExcluded"
]

EXTRACTED_ROOT_NAME = ""

GIT_AUTH_MAX_RETRIES = 3


# =======================================
# Helpers
# =======================================

def log(message: str) -> None:
    print(f"\n[INFO] {message}")


def die(message: str) -> None:
    print(f"\nERROR: {message}", file=sys.stderr)
    sys.exit(1)


def run_cmd(cmd, cwd=None, check=True, capture_output=True):
    log("Running: " + " ".join(map(str, cmd)))
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        shell=False,
        capture_output=capture_output,
    )

    if capture_output and result.stdout.strip():
        print(result.stdout.strip())

    if result.returncode != 0 and check:
        if capture_output and result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        die(f"Command failed with exit code {result.returncode}")

    return result


def run_git_cmd_with_retry(cmd, cwd=None, capture_output=True, purpose="Git operation"):
    for attempt in range(1, GIT_AUTH_MAX_RETRIES + 1):
        result = run_cmd(cmd, cwd=cwd, check=False, capture_output=capture_output)

        if result.returncode == 0:
            return result

        if attempt < GIT_AUTH_MAX_RETRIES:
            root = Tk()
            root.withdraw()
            retry = messagebox.askretrycancel(
                "Git authentication",
                f"{purpose} failed.\n\nPlease complete login if prompted and retry."
            )
            root.destroy()

            if not retry:
                die("Operation cancelled.")
        else:
            die(f"{purpose} failed after retries.")


def select_tar_file() -> Path:
    root = Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Select package",
        filetypes=[("Tar files", "*.tar.gz *.tgz")]
    )
    root.destroy()

    if not file_path:
        die("No file selected")

    return Path(file_path)


def ask_text(title, prompt, default=""):
    root = Tk()
    root.withdraw()
    val = simpledialog.askstring(title, prompt, initialvalue=default)
    root.destroy()

    if val is None:
        die("Cancelled")

    return val.strip()


# 🔥 UPDATED (LIMIT TO 20)
def ask_target_branch(branches, default_branch):
    MAX_DISPLAY = 20
    display = branches[:MAX_DISPLAY]

    text = "\n".join(display)
    if len(branches) > MAX_DISPLAY:
        text += "\n...\n(more branches not shown)"

    while True:
        val = ask_text(
            "Select target branch",
            f"Branches:\n\n{text}\n\nEnter target [{default_branch}]:",
            default_branch
        )

        val = val or default_branch

        if val in branches:
            return val

        messagebox.showerror("Error", f"Branch '{val}' does not exist")


def get_remote_branches():
    result = run_git_cmd_with_retry(
        ["git", "ls-remote", "--heads", GIT_REMOTE_URL],
        purpose="Fetching branches"
    )

    branches = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("refs/heads/"):
            branches.append(parts[1].replace("refs/heads/", ""))

    return sorted(branches)


def get_unique_branch_name(name, branches):
    if name not in branches:
        return name

    i = 1
    while True:
        new = f"{name}-{i}"
        if new not in branches:
            return new
        i += 1


def extract_tar(tar_file, dest):
    with tarfile.open(tar_file, "r:*") as tar:
        tar.extractall(dest)


def detect_content_dir(extract_dir):
    items = list(extract_dir.iterdir())
    if len(items) == 1 and items[0].is_dir():
        return items[0]
    return extract_dir


def copy_tree(src, dst):
    for item in src.iterdir():
        if item.name == ".git":
            continue

        target = dst / item.name

        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def main():
    tar_file = select_tar_file()

    branches = get_remote_branches()

    target_branch = ask_target_branch(branches, DEFAULT_TARGET_BRANCH)

    requested_source = ask_text(
        "Source branch",
        "Enter source branch:",
        DEFAULT_SOURCE_BRANCH
    )

    source_branch = get_unique_branch_name(requested_source, branches)

    if source_branch != requested_source:
        messagebox.showinfo(
            "Branch updated",
            f"Using '{source_branch}' instead (already exists)"
        )

    title = ask_text(
        "MR title",
        "Enter MR title:",
        f"Import into {target_branch}"
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        extract_dir = tmp / "extract"
        repo_dir = tmp / "repo"

        extract_dir.mkdir()

        log("Extracting...")
        extract_tar(tar_file, extract_dir)

        content_dir = detect_content_dir(extract_dir)

        log("Cloning...")
        run_git_cmd_with_retry(
            ["git", "clone", "--branch", target_branch, GIT_REMOTE_URL, str(repo_dir)],
            purpose="Clone"
        )

        run_cmd(["git", "checkout", "-b", source_branch], cwd=repo_dir)

        log("Copying files...")
        copy_tree(content_dir, repo_dir)

        run_cmd(["git", "add", "-A"], cwd=repo_dir)

        diff = run_cmd(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_dir,
            check=False
        )

        if diff.returncode == 0:
            messagebox.showinfo("No changes", "Nothing to commit")
            return

        run_cmd(["git", "commit", "-m", "Import"], cwd=repo_dir)

        run_git_cmd_with_retry(
            ["git", "push", "-u", "origin", source_branch],
            cwd=repo_dir,
            purpose="Push"
        )

        url = (
            f"https://gitlab.com/{GITLAB_PROJECT_PATH}/-/merge_requests/new?"
            f"merge_request[source_branch]={source_branch}&"
            f"merge_request[target_branch]={target_branch}&"
            f"merge_request[title]={urllib.parse.quote(title)}"
        )

        webbrowser.open(url)
        messagebox.showinfo("Done", f"MR opened:\n{url}")


if __name__ == "__main__":
    main()