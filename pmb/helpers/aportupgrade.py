# Copyright 2020 Luca Weiss
# SPDX-License-Identifier: GPL-3.0-or-later
import datetime
import fnmatch
import logging
import os
import re
import urllib
from typing import List, Optional

import pmb.helpers.file
import pmb.helpers.http
import pmb.helpers.pmaports

req_headers = None
req_headers_github = None

ANITYA_API_BASE = "https://release-monitoring.org/api/v2"
GITHUB_API_BASE = "https://api.github.com"
GITLAB_HOSTS = [
    "https://gitlab.com",
    "https://invent.kde.org",
    "https://source.puri.sm",
    "https://gitlab.freedesktop.org",
]


def init_req_headers() -> None:
    global req_headers
    global req_headers_github
    # Only initialize them once
    if req_headers is not None and req_headers_github is not None:
        return
    # Generic request headers
    req_headers = {'User-Agent': 'pmbootstrap/{} aportupgrade'.format(pmb.config.version)}

    # Request headers specific to GitHub
    req_headers_github = dict(req_headers)
    if os.getenv("GITHUB_TOKEN") is not None:
        req_headers_github['Authorization'] = 'token ' + os.getenv("GITHUB_TOKEN")
    else:
        logging.info("NOTE: Consider using a GITHUB_TOKEN environment variable to increase your rate limit")


def get_github_ref_arg(repo_name: str, branches: List[str],
                       ref: Optional[str]) -> str:
    """
    Get the branch to query for the latest commit
    :param repo_name: the repository name
    :param branches: list of branches to use in order of preference
    :param ref: TODO
    :returns: e.g. "?sha=bionic" or ""
    """
    # Return argument with ref if specified
    if ref is not None:
        return "?sha=" + ref

    # Short circuit if no branch was requested
    if len(branches) == 0:
        return ""

    # Get a list of branches to see if one of the requested branches exist
    # We can get max. 100 branches, see https://docs.github.com/en/rest/reference/repos#list-branches
    branches_remote = pmb.helpers.http.retrieve_json(
        GITHUB_API_BASE + "/repos/" + repo_name + "/branches?per_page=100",
        headers=req_headers_github)
    branch_names_remote = list(map(lambda x: x["name"], branches_remote))
    logging.verbose(f"Available branches: {', '.join(branch_names_remote)}")

    for branch in branches:
        if branch in branch_names_remote:
            return "?sha=" + branch
    # Return no branch if no matching was found
    logging.info(f"No matching git branches for requested {', '.join(branches)} found.")
    return ""


def get_package_version_info_github(repo_name: str, branches: List[str],
                                    ref: Optional[str]):
    logging.debug("Trying GitHub repository: {}".format(repo_name))

    # Get the URL argument to request a special branch, if needed
    ref_arg = get_github_ref_arg(repo_name, branches, ref)

    # Get the commits for the repository
    commits = pmb.helpers.http.retrieve_json(
        GITHUB_API_BASE + "/repos/" + repo_name + "/commits" + ref_arg,
        headers=req_headers_github)
    latest_commit = commits[0]
    commit_date = latest_commit["commit"]["committer"]["date"]
    # Extract the time from the field
    date = datetime.datetime.strptime(commit_date, "%Y-%m-%dT%H:%M:%SZ")
    return {
        "sha": latest_commit["sha"],
        "date": date,
    }


def get_gitlab_ref_arg(gitlab_host: str, repo_name_safe: str,
                       branches: List[str], ref: Optional[str]) -> str:
    """
    Get the branch to query for the latest commit
    :param gitlab_host: the base url of the gitlab instance
    :param repo_name_safe: the url-quoted repository name
    :param branches: list of branches to use in order of preference
    :param ref: TODO
    :returns: e.g. "?ref_name=librem5-3-34-1" or ""
    """
    # Return argument with ref if specified
    if ref is not None:
        return "?ref_name=" + ref

    # Short circuit if no branch was requested
    if len(branches) == 0:
        return ""

    # Get a list of branches to see if one of the requested branches exist
    # We can get max. 100 branches, see https://docs.gitlab.com/ee/api/README.html#pagination
    branches_remote = pmb.helpers.http.retrieve_json(
        gitlab_host + "/api/v4/projects/" + repo_name_safe + "/repository/branches?per_page=100",
        headers=req_headers)
    branch_names_remote = list(map(lambda x: x["name"], branches_remote))
    logging.verbose(f"Available branches: {', '.join(branch_names_remote)}")

    for branch in branches:
        if branch in branch_names_remote:
            return "?ref_name=" + branch
    # Return no branch if no matching was found
    logging.info(f"No matching git branches for requested {', '.join(branches)} found.")
    return ""


def get_package_version_info_gitlab(gitlab_host: str, repo_name: str,
                                    branches: List[str], ref: Optional[str]):
    logging.debug("Trying GitLab repository: {}".format(repo_name))

    repo_name_safe = urllib.parse.quote(repo_name, safe='')

    # Get the URL argument to request a special branch, if needed
    ref_arg = get_gitlab_ref_arg(gitlab_host, repo_name_safe, branches, ref)

    # Get the commits for the repository
    commits = pmb.helpers.http.retrieve_json(
        gitlab_host + "/api/v4/projects/" + repo_name_safe + "/repository/commits" + ref_arg,
        headers=req_headers)
    latest_commit = commits[0]
    commit_date = latest_commit["committed_date"]
    # Extract the time from the field
    # 2019-10-14T09:32:00.000Z / 2019-12-27T07:58:53.000-05:00
    date = datetime.datetime.strptime(commit_date, "%Y-%m-%dT%H:%M:%S.000%z")
    return {
        "sha": latest_commit["id"],
        "date": date,
    }


def upgrade_git_package(args, pkgname: str, package) -> bool:
    """
    Update _commit/pkgver/pkgrel in a git-APKBUILD (or pretend to do it if args.dry is set).
    :param pkgname: the package name
    :param package: a dict containing package information
    :returns: if something (would have) been changed
    """
    # Get the wanted source line
    source = package["source"][0]
    source = re.split(r"::", source)
    if 1 <= len(source) <= 2:
        source = source[-1]
    else:
        raise RuntimeError("Unhandled number of source elements. Please open a bug report: {}".format(source))

    verinfo = None

    branches = []
    if args.branch is not None:
        branches = args.branch.split(",")

    github_match = re.match(r"https://github\.com/(.+)/(?:archive|releases)", source)
    gitlab_match = re.match(r"(" + '|'.join(GITLAB_HOSTS) + ")/(.+)/-/archive/", source)
    if github_match:
        verinfo = get_package_version_info_github(github_match.group(1), branches, args.ref)
    elif gitlab_match:
        verinfo = get_package_version_info_gitlab(gitlab_match.group(1), gitlab_match.group(2), branches, args.ref)

    if verinfo is None:
        # ignore for now
        logging.warning("{}: source not handled: {}".format(pkgname, source))
        return False

    # Get the new commit sha
    sha = package["_commit"]
    sha_new = verinfo["sha"]

    # Format the new pkgver, keep the value before _git the same
    pkgver = package["pkgver"]
    pkgver_match = re.match(r"([\d.]+)_git", pkgver)
    date_pkgver = verinfo["date"].strftime("%Y%m%d")
    pkgver_new = pkgver_match.group(1) + "_git" + date_pkgver

    # pkgrel will be zero
    pkgrel = int(package["pkgrel"])
    pkgrel_new = 0

    if sha == sha_new:
        logging.info("{}: up-to-date".format(pkgname))
        return False

    logging.info("{}: upgrading pmaport".format(pkgname))
    if args.dry:
        logging.info("  Would change _commit from {} to {}".format(sha, sha_new))
        logging.info("  Would change pkgver from {} to {}".format(pkgver, pkgver_new))
        logging.info("  Would change pkgrel from {} to {}".format(pkgrel, pkgrel_new))
        return True

    pmb.helpers.file.replace_apkbuild(args, pkgname, "pkgver", pkgver_new)
    pmb.helpers.file.replace_apkbuild(args, pkgname, "pkgrel", pkgrel_new)
    pmb.helpers.file.replace_apkbuild(args, pkgname, "_commit", sha_new, True)
    return True


def upgrade_stable_package(args, pkgname: str, package) -> bool:
    """
    Update _commit/pkgver/pkgrel in an APKBUILD (or pretend to do it if args.dry is set).

    :param pkgname: the package name
    :param package: a dict containing package information
    :returns: if something (would have) been changed
    """
    projects = pmb.helpers.http.retrieve_json(ANITYA_API_BASE + "/projects/?name=" + pkgname, headers=req_headers)
    if projects["total_items"] < 1:
        # There is no Anitya project with the package name.
        # Looking up if there's a custom mapping from postmarketOS package name to Anitya project name.
        mappings = pmb.helpers.http.retrieve_json(
            ANITYA_API_BASE + "/packages/?distribution=postmarketOS&name=" + pkgname, headers=req_headers)
        if mappings["total_items"] < 1:
            logging.warning("{}: failed to get Anitya project".format(pkgname))
            return False
        project_name = mappings["items"][0]["project"]
        projects = pmb.helpers.http.retrieve_json(
            ANITYA_API_BASE + "/projects/?name=" + project_name, headers=req_headers)

    # Get the first, best-matching item
    project = projects["items"][0]

    # Check that we got a version number
    if project["version"] is None:
        logging.warning("{}: got no version number, ignoring".format(pkgname))
        return False

    # Compare the pmaports version with the project version
    if package["pkgver"] == project["version"]:
        logging.info("{}: up-to-date".format(pkgname))
        return False

    pkgver = package["pkgver"]
    pkgver_new = project["version"]

    pkgrel = package["pkgrel"]
    pkgrel_new = 0

    if not pmb.parse.version.validate(pkgver_new):
        logging.warning("{}: would upgrade to invalid pkgver: {}, ignoring".format(pkgname, pkgver_new))
        return False

    logging.info("{}: upgrading pmaport".format(pkgname))
    if args.dry:
        logging.info("  Would change pkgver from {} to {}".format(pkgver, pkgver_new))
        logging.info("  Would change pkgrel from {} to {}".format(pkgrel, pkgrel_new))
        return True

    pmb.helpers.file.replace_apkbuild(args, pkgname, "pkgver", pkgver_new)
    pmb.helpers.file.replace_apkbuild(args, pkgname, "pkgrel", pkgrel_new)
    return True


def upgrade(args, pkgname, git=True, stable=True) -> bool:
    """
    Find new versions of a single package and upgrade it.

    :param pkgname: the name of the package
    :param git: True if git packages should be upgraded
    :param stable: True if stable packages should be upgraded
    :returns: if something (would have) been changed
    """
    # Initialize request headers
    init_req_headers()

    package = pmb.helpers.pmaports.get(args, pkgname)
    # Run the correct function
    if "_git" in package["pkgver"]:
        if git:
            return upgrade_git_package(args, pkgname, package)
    else:
        if stable:
            return upgrade_stable_package(args, pkgname, package)


def upgrade_all(args) -> None:
    """
    Upgrade all packages, based on args.all, args.all_git and args.all_stable.
    """
    for pkgname in pmb.helpers.pmaports.get_list(args):
        # Always ignore postmarketOS-specific packages that have no upstream source
        skip = False
        for pattern in pmb.config.upgrade_ignore:
            if fnmatch.fnmatch(pkgname, pattern):
                skip = True
        if skip:
            continue

        upgrade(args, pkgname, args.all or args.all_git, args.all or args.all_stable)
