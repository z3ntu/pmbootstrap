"""
Copyright 2019 Oliver Smith

This file is part of pmbootstrap.

pmbootstrap is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

pmbootstrap is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with pmbootstrap.  If not, see <http://www.gnu.org/licenses/>.
"""
import logging
import os
import re

import pmb.aportgen.binutils
import pmb.aportgen.busybox_static
import pmb.aportgen.device
import pmb.aportgen.gcc
import pmb.aportgen.linux
import pmb.aportgen.musl
import pmb.aportgen.grub_efi
#import pmb.aportgen.qt5
import pmb.aportgen.generic
import pmb.config
import pmb.helpers.cli


def properties(cross_pkgname):
    """
    Get the `pmb.config.aportgen` properties for the aport generator, based on
    the cross_pkgname prefix.

    Example: "musl-armhf" => ("musl", "cross", {"confirm_overwrite": False})

    :param cross_pkgname: package name
    :returns: (pkgname, arch, folder, options)
    """
    pmb.config.build_device_architectures
    pattern = re.compile("(.*)-(armhf|armv7|aarch64|x86_64|x86)")
    match = pattern.match(cross_pkgname)
    if match is None:
        raise ValueError("No generator available for " + cross_pkgname + "!")
    pkgname, arch = match.groups()
    return (pkgname, arch, "cross", {"confirm_overwrite": False})

    # for folder, options in pmb.config.aportgen.items():
    #     for prefix in options["prefixes"]:
    #         if pkgname.startswith(prefix):
    #             return (prefix, folder, options)
    # logging.info("NOTE: aportgen is for generating postmarketOS specific"
    #              " aports, such as the cross-compiler related packages"
    #              " or the linux kernel fork packages.")
    # logging.info("NOTE: If you wanted to package new software in general, try"
    #              " 'pmbootstrap newapkbuild' to generate a template.")
    # raise ValueError("No generator available for " + pkgname + "!")


def generate(args, cross_pkgname):
    # Confirm overwrite
    pkgname, arch, folder, options = properties(cross_pkgname)
    path_target = args.aports + "/" + folder + "/" + cross_pkgname
    if options["confirm_overwrite"] and os.path.exists(path_target):
        logging.warning("WARNING: Target folder already exists: " + path_target)
        if not pmb.helpers.cli.confirm(args, "Continue and overwrite?"):
            raise RuntimeError("Aborted.")

    # Run pmb.aportgen.PREFIX.generate()
    if os.path.exists(args.work + "/aportgen"):
        pmb.helpers.run.user(args, ["rm", "-r", args.work + "/aportgen"])
    generator = getattr(pmb.aportgen, pkgname.replace("-", "_"), None)
    if generator is None:
        generator = pmb.aportgen.generic
    generator.generate(args, cross_pkgname, pkgname, arch)

    # Move to the aports folder
    if os.path.exists(path_target):
        pmb.helpers.run.user(args, ["rm", "-r", path_target])
    pmb.helpers.run.user(
        args, ["mv", args.work + "/aportgen", path_target])
