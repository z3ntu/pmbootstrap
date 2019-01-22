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
import glob
import logging
import os

import pmb.aportgen.core
import pmb.chroot.apk
import pmb.chroot.apk_static
import pmb.helpers.run
import pmb.parse.apkindex


def generate(args, cross_pkgname, pkgname, arch):
    # Parse subpackages of pkgname from APKINDEX
    subpackages = pmb.parse.apkindex.subpackages(args, pkgname)
    if len(subpackages) == 0:
        subpackages = [pkgname]

    # Parse target version from APKINDEX
    package_data = pmb.parse.apkindex.package(args, pkgname, arch)
    version = package_data["version"]
    pkgver = version.split("-r")[0]
    pkgrel = version.split("-r")[1]

    url = package_data["url"]
    pkglicense = package_data["license"]
    pkgdesc = package_data["pkgdesc"]
    depends = package_data["depends"]

    # Install target in chroot to get verified apks
    pmb.chroot.apk.install(args, subpackages, "buildroot_" + arch)

    # Architectures to build this package for
    arches = list(pmb.config.build_device_architectures)
    arches.remove(arch)

    # Copy the apk files to the distfiles cache
    for subpkgname in subpackages:
        pattern = (args.work + "/cache_apk_" + arch + "/" + subpkgname +
                   "-" + version + ".*.apk")
        glob_result = glob.glob(pattern)
        if not len(glob_result):
            raise RuntimeError("Could not find aport " + pattern + "!"
                               " Update your aports_upstream git repo"
                               " to the latest version, delete your http cache"
                               " (pmbootstrap zap -hc) and try again.")
        path = glob_result[0]
        path_target = (args.work + "/cache_distfiles/" + subpkgname + "-" +
                       version + "-" + arch + ".apk")
        if not os.path.exists(path_target):
            pmb.helpers.run.root(args, ["cp", path, path_target])

    # Prepare "subpackages" line
    subpkgs = []
    for subpkgname in subpackages:
        if subpkgname == pkgname:
            continue
        subpkgs.append(subpkgname + "-" + arch + ":package_" + subpkgname.replace("-", "_"))

    # Prepare "sources" line
    sourcestr = ""
    for subpkgname in subpackages:
        sourcestr += "    " + subpkgname + "-$pkgver-r$pkgrel-$_arch.apk::$_mirror/edge/main/$_arch/" + subpkgname + "-$pkgver-r$pkgrel.apk\n"

    # Prepare "depends" line
    # print("Depends: " + str(depends))
    crossdepends = []
    for depend in depends:
        # We only care about .so dependencies
        if not depend.startswith("so:"):
            continue
        providers = pmb.parse.apkindex.providers(args, depend, arch, must_exist=True)
        # print("Providers: " + str(providers))
        # print("len: " + str(len(providers)))
        # Add name of provider
        crossdep = list(providers.items())[0][0]
        # ERROR: libstdc++-armhf-8.2.0-r2: trying to overwrite usr/armv6-alpine-linux-muslgnueabihf/lib/libstdc++.so.6 owned by g++-armhf-8.2.0-r2.
        if crossdep == "libstdc++" or crossdep == "libgcc":
            continue
        crossdepends.append(crossdep + "-" + arch)

    # Prepare subpackage-specific package() functions
    packagefuncstr = """
        package() {{
            mkdir -p "$pkgdir/usr/$_target"
            cd "$pkgdir/usr/$_target"
            tar -xf $srcdir/{0}-$pkgver-r$pkgrel-$_arch.apk
            rm .PKGINFO .SIGN.*

            # make the directory structure be /usr/$_target/{{lib,share}}
            if [ -d usr/ ]; then
              # See https://unix.stackexchange.com/a/172402/138490
              cp -rl usr/* .
              rm -r usr
            fi
        }}
    """.format(pkgname)
    for subpkgname in subpackages:
        if subpkgname == pkgname:
            continue
        packagefuncstr += """
        {0}() {{
            mkdir -p "$subpkgdir/usr/$_target"
            cd "$subpkgdir/usr/$_target"
            tar -xf $srcdir/{1}-$pkgver-r$pkgrel-$_arch.apk
            rm .PKGINFO .SIGN.*

            # make the directory structure be /usr/$_target/{{lib,share}}
            if [ -d usr/ ]; then
              # See https://unix.stackexchange.com/a/172402/138490
              cp -rl usr/* .
              rm -r usr
            fi

            # fix prefix of pkg-config files
            find "$subpkgdir"/usr/$_target/lib/pkgconfig -name "*.pc" -exec \
                sed -i 's|prefix=/usr$|prefix=/usr/armv6-alpine-linux-muslgnueabihf|' {{}} \; || true
            # fix path to host binaries of Qt5
            sed -i 's|host_bins=.*|host_bins=/usr/lib/qt5/bin|' "$subpkgdir"/usr/$_target/lib/pkgconfig/Qt5Core.pc || true
        }}
        """.format("package_" + subpkgname.replace("-", "_"), subpkgname)

    # Hash the distfiles
    cmd = ["sha512sum"]
    for subpkgname in subpackages:
        cmd.append(subpkgname + "-" + version + "-" + arch + ".apk")
    hashes = pmb.chroot.user(args, cmd, "buildroot_" + arch,
                             "/var/cache/distfiles", output_return=True)

    # Write the APKBUILD
    pmb.helpers.run.user(args, ["mkdir", "-p", args.work + "/aportgen"])
    with open(args.work + "/aportgen/APKBUILD", "w", encoding="utf-8") as handle:
        # Variables
        handle.write("# Automatically generated aport, do not edit!\n"
                     "# Generator: pmbootstrap aportgen " + cross_pkgname + "\n"
                     "\n"
                     "pkgname=\"" + cross_pkgname + "\"\n"
                     "pkgver=\"" + pkgver + "\"\n"
                     "pkgrel=" + pkgrel + "\n"
                     "arch=\"" + " ".join(arches) + "\"\n"
                     "subpackages=\"" + " ".join(subpkgs) + "\"\n"
                     "\n"
                     "_arch=\"" + arch + "\"\n"
                     "_mirror=\"" + args.mirror_alpine + "\"\n"
                     "\n"
                     "url=\"" + url + "\"\n"
                     "license=\"" + pkglicense + "\"\n"
                     "options=\"!check !strip\"\n"
                     "pkgdesc=\"" + pkgdesc + " for $_arch\"\n"
                     "depends=\"" + " ".join(crossdepends) + "\"\n"
                     "\n"
                     "_target=\"$(arch_to_hostspec $_arch)\"\n"
                     "\n"
                     "source=\"\n" + sourcestr + "\"\n"
                     )
        # Write package() functions
        for line in packagefuncstr.split("\n"):
            handle.write(line[8:] + "\n")

        # Hashes
        handle.write("sha512sums=\"" + hashes.rstrip() + "\"\n")

    maports = []
    for crossdepend in crossdepends:
        if not os.path.isfile(args.aports + "/cross/" + crossdepend + "/APKBUILD"):
            maports.append(crossdepend)
    if len(maports) != 0:
        logging.info("Missing cross APKBUILDs: run 'pmbootstrap aportgen " + " ".join(maports) + "' to generate them.")
