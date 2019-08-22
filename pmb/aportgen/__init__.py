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
# import pmb.aportgen.busybox_static
import pmb.aportgen.device
import pmb.aportgen.gcc
import pmb.aportgen.generic
# import pmb.aportgen.grub_efi
import pmb.aportgen.linux
# import pmb.aportgen.musl
import pmb.config
import pmb.helpers.cli


def properties(gen_pkgname):
    """
    Get the `pmb.config.aportgen` properties for the aport generator, based on
    the cross_pkgname prefix.

    Example: "musl-armhf" => ("musl", "cross", {"confirm_overwrite": False})
    Example: "gcc4-armv7" => ("gcc", "armv7", {"confirm_overwrite": False})

    :param gen_pkgname: package name
    :returns: (pkgname, folder, options)
    """
    # Try package-specific generators first
    for folder, options in pmb.config.aportgen.items():
        for prefix in options["prefixes"]:
            if gen_pkgname.startswith(prefix):
                return prefix, folder, options

    logging.info("NOTE: aportgen is for generating postmarketOS specific"
                 " aports, such as the cross-compiler related packages"
                 " or the linux kernel fork packages.")
    logging.info("NOTE: If you wanted to package new software in general, try"
                 " 'pmbootstrap newapkbuild' to generate a template.")
    raise ValueError("No generator available for " + gen_pkgname + "!")


def generate(args, gen_pkgname):
    # Confirm overwrite
    prefix, folder, options = properties(gen_pkgname)
    path_target = args.aports + "/" + folder + "/" + gen_pkgname
    if options["confirm_overwrite"] and os.path.exists(path_target):
        logging.warning("WARNING: Target folder already exists: " + path_target)
        if not pmb.helpers.cli.confirm(args, "Continue and overwrite?"):
            raise RuntimeError("Aborted.")

    # Run pmb.aportgen.PREFIX.generate()
    if os.path.exists(args.work + "/aportgen"):
        pmb.helpers.run.user(args, ["rm", "-r", args.work + "/aportgen"])
    generator = getattr(pmb.aportgen, prefix.replace("-", "_"), None)
    if generator is None:
        generator = pmb.aportgen.generic

    # Cross generators use pkgname and arch parameters as well
    if folder == "cross":
        match = re.match(r"(.*)-(armhf|armv7|aarch64|x86|x86_64)", gen_pkgname)
        if match is None:
            raise RuntimeError("Failed to extract pkgname and arch from gen_pkgname!")
        pkgname, arch = match.groups()
        generator.generate(args, gen_pkgname, pkgname, arch)
    elif folder == "device":
        generator.generate(args, gen_pkgname)

    # Move to the aports folder
    if os.path.exists(path_target):
        pmb.helpers.run.user(args, ["rm", "-r", path_target])
    pmb.helpers.run.user(
        args, ["mv", args.work + "/aportgen", path_target])
