# Copyright 2020 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import argparse
import copy

try:
    import argcomplete
except ImportError:
    argcomplete = False

import pmb.config
import pmb.parse.arch
import pmb.helpers.args
import pmb.helpers.pmaports

""" This file is about parsing command line arguments passed to pmbootstrap, as
    well as generating the help pages (pmbootstrap -h). All this is done with
    Python's argparse. The parsed arguments get extended and finally stored in
    the "args" variable, which is prominently passed to most functions all
    over the pmbootstrap code base.

    See pmb/helpers/args.py for more information about the args variable. """


def arguments_export(subparser):
    ret = subparser.add_parser("export", help="create convenience symlinks"
                               " to generated image files (system, kernel,"
                               " initramfs, boot.img, ...)")

    ret.add_argument("export_folder", help="export folder, defaults to"
                                           " /tmp/postmarketOS-export",
                     default="/tmp/postmarketOS-export", nargs="?")
    ret.add_argument("--odin", help="odin flashable tar"
                                    " (boot.img/kernel+initramfs only)",
                     action="store_true", dest="odin_flashable_tar")
    ret.add_argument("--flavor", default=None)
    ret.add_argument("--no-install", dest="autoinstall", default=True,
                     help="skip updating kernel/initfs", action="store_false")
    return ret


def arguments_flasher(subparser):
    ret = subparser.add_parser("flasher", help="flash something to the"
                               " target device")
    ret.add_argument("--method", help="override flash method",
                     dest="flash_method", default=None)
    sub = ret.add_subparsers(dest="action_flasher")
    sub.required = True

    # Boot, flash kernel
    boot = sub.add_parser("boot", help="boot a kernel once")
    boot.add_argument("--cmdline", help="override kernel commandline")
    flash_kernel = sub.add_parser("flash_kernel", help="flash a kernel")
    for action in [boot, flash_kernel]:
        action.add_argument("--flavor", default=None)
        action.add_argument("--no-install", dest="autoinstall", default=True,
                            help="skip updating kernel/initfs", action="store_false")
    flash_kernel.add_argument("--partition", default=None,
                              help="partition to flash the kernel to (defaults"
                                   " to deviceinfo_flash_*_partition_kernel)")

    # Flash rootfs
    flash_rootfs = sub.add_parser("flash_rootfs", aliases=["flash_system"],
                                  help="flash the rootfs to a partition on the"
                                  " device (partition layout does not get"
                                  " changed)")
    flash_rootfs.add_argument("--partition", default=None,
                              help="partition to flash the rootfs to (defaults"
                                   " to deviceinfo_flash_*_partition_system,"
                                   " 'userdata' on Android may have more"
                                   " space)")

    # Flash vbmeta
    flash_vbmeta = sub.add_parser("flash_vbmeta",
                                  help="generate and flash AVB 2.0 image with disable"
                                       " verification flag set to a partition on the"
                                       " device (typically called vbmeta)")
    flash_vbmeta.add_argument("--partition", default=None,
                              help="partition to flash the vbmeta to (defaults"
                                   " to deviceinfo_flash_*_partition_vbmeta")

    # Actions without extra arguments
    sub.add_parser("sideload", help="sideload recovery zip")
    sub.add_parser("list_flavors", help="list installed kernel flavors" +
                   " inside the device rootfs chroot on this computer")
    sub.add_parser("list_devices", help="show connected devices")

    return ret


def arguments_initfs(subparser):
    ret = subparser.add_parser(
        "initfs", help="do something with the initramfs")
    sub = ret.add_subparsers(dest="action_initfs")

    # hook ls
    sub.add_parser(
        "hook_ls",
        help="list available and installed hook packages")

    # hook add/del
    hook_add = sub.add_parser("hook_add", help="add a hook package")
    hook_del = sub.add_parser("hook_del", help="uninstall a hook package")
    for action in [hook_add, hook_del]:
        action.add_argument("hook", help="name of the hook aport, without the"
                            " '" + pmb.config.initfs_hook_prefix + "' prefix, for example: 'debug-shell'")

    # ls, build, extract
    ls = sub.add_parser("ls", help="list initramfs contents")
    build = sub.add_parser("build", help="(re)build the initramfs")
    extract = sub.add_parser(
        "extract",
        help="extract the initramfs to a temporary folder")
    for action in [ls, build, extract]:
        action.add_argument(
            "--flavor",
            default=None,
            help="name of the kernel flavor (run 'pmbootstrap flasher list_flavors'"
            " to get a list of all installed flavors")

    return ret


def arguments_qemu(subparser):
    ret = subparser.add_parser("qemu")
    ret.add_argument("--cmdline", help="override kernel commandline")
    ret.add_argument("--image-size", default="4G",
                     help="set rootfs size, e.g. 2048M or 2G (default: 4G)")
    ret.add_argument("-m", "--memory", type=int, default=1024,
                     help="guest RAM (default: 1024)")
    ret.add_argument("-p", "--port", type=int, default=2222,
                     help="SSH port (default: 2222)")

    ret.add_argument("--no-kvm", dest="qemu_kvm", default=True, action='store_false',
                     help="Avoid using hardware-assisted virtualization with KVM "
                     "even when available (SLOW!)")
    ret.add_argument("--cpu", dest="qemu_cpu",
                     help="Override emulated QEMU CPU. By default, the host CPU "
                     "will be emulated when using KVM and the QEMU default otherwise "
                     "(usually a CPU with minimal features). "
                     "A useful value is 'max' (emulate all features that are available), "
                     "use --cpu help to get a list of possible values from QEMU.")

    ret.add_argument("--tablet", dest="qemu_tablet", action='store_true',
                     default=False, help="Use 'tablet' instead of 'mouse' input "
                     "for QEMU. The tablet input device automatically grabs/releases "
                     "the mouse when moving in/out of the QEMU window. "
                     "(Note: For some reason the mouse position is not reported "
                     "correctly with this in some cases...)")

    ret.add_argument("--display", dest="qemu_display", choices=["sdl", "gtk", "none"],
                     help="QEMU's display parameter (default: sdl,gl=on)",
                     default="sdl", nargs="?")
    ret.add_argument("--no-gl", dest="qemu_gl", default=True, action='store_false',
                     help="Avoid using GL for accelerating graphics in QEMU "
                     "(use software rasterizer, slow!)")
    ret.add_argument("--video", dest="qemu_video", default="1024x768@60",
                     help="Video resolution for QEMU (WidthxHeight@RefreshRate). "
                     "Default is 1024x768@60.")

    ret.add_argument("--audio", dest="qemu_audio", choices=["alsa", "pa", "sdl"],
                     help="QEMU's audio backend (default: none)",
                     default=None, nargs="?")

    ret.add_argument("--host-qemu", dest="host_qemu", action='store_true',
                     help="Use the host system's qemu")

    return ret


def arguments_pkgrel_bump(subparser):
    ret = subparser.add_parser("pkgrel_bump", help="increase the pkgrel to"
                               " indicate that a package must be rebuilt"
                               " because of a dependency change")
    ret.add_argument("--dry", action="store_true", help="instead of modifying"
                     " APKBUILDs, exit with >0 when a package would have been"
                     " bumped")

    # Mutually exclusive: "--auto" or package names
    mode = ret.add_mutually_exclusive_group(required=True)
    mode.add_argument("--auto", action="store_true", help="all packages which"
                      " depend on a library which had an incompatible update"
                      " (libraries with a soname bump)")
    mode.add_argument("packages", nargs="*", default=[])
    return ret


def arguments_aportupgrade(subparser):
    ret = subparser.add_parser("aportupgrade")
    ret.add_argument("--dry", action="store_true", help="instead of modifying APKBUILDs,"
                     " print the changes that would be made")
    ret.add_argument("--branch", help="git branch to use. if none is specified, the default branch"
                                      " gets used. you can specify multiple by separating them with"
                                      " a comma. the first found will be used")

    # Mutually exclusive: "--all" or package names
    mode = ret.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all", action="store_true", help="iterate through all packages")
    mode.add_argument("--all-stable", action="store_true", help="iterate through all non-git packages")
    mode.add_argument("--all-git", action="store_true", help="iterate through all git packages")
    mode.add_argument("packages", nargs="*", default=[])
    return ret


def arguments_newapkbuild(subparser):
    """
    Wrapper for Alpine's "newapkbuild" command.

    Most parameters will get directly passed through, and they are defined in
    "pmb/config/__init__.py". That way they can be used here and when passing
    them through in "pmb/helpers/frontend.py". The order of the parameters is
    kept the same as in "newapkbuild -h".
    """
    sub = subparser.add_parser("newapkbuild", help="get a template to package"
                               " new software")
    sub.add_argument("--folder", help="set postmarketOS aports folder"
                     " (default: main)", default="main")

    # Passthrough: Strings (e.g. -d "my description")
    for entry in pmb.config.newapkbuild_arguments_strings:
        sub.add_argument(entry[0], dest=entry[1], help=entry[2])

    # Passthrough: Package type switches (e.g. -C for CMake)
    group = sub.add_mutually_exclusive_group()
    for entry in pmb.config.newapkbuild_arguments_switches_pkgtypes:
        group.add_argument(entry[0], dest=entry[1], help=entry[2],
                           action="store_true")

    # Passthrough: Other switches (e.g. -c for copying sample files)
    for entry in pmb.config.newapkbuild_arguments_switches_other:
        sub.add_argument(entry[0], dest=entry[1], help=entry[2],
                         action="store_true")

    # Force switch
    sub.add_argument("-f", dest="force", action="store_true",
                     help="force even if directory already exists")

    # Passthrough: PKGNAME[-PKGVER] | SRCURL
    sub.add_argument("pkgname_pkgver_srcurl",
                     metavar="PKGNAME[-PKGVER] | SRCURL",
                     help="set either the package name (optionally with the"
                     " PKGVER at the end, e.g. 'hello-world-1.0') or the"
                     " download link to the source archive")


def arguments_kconfig(subparser):
    # Allowed architectures
    arch_native = pmb.parse.arch.alpine_native()
    arch_choices = set(pmb.config.build_device_architectures + [arch_native])

    # Kconfig subparser
    ret = subparser.add_parser("kconfig", help="change or edit kernel configs")
    sub = ret.add_subparsers(dest="action_kconfig")
    sub.required = True

    # "pmbootstrap kconfig check"
    check = sub.add_parser("check", help="check kernel aport config")
    check.add_argument("-f", "--force", action="store_true", help="check all"
                       " kernels, even the ones that would be ignored by"
                       " default")
    check.add_argument("--arch", choices=arch_choices, dest="arch")
    check.add_argument("--file", action="store_true", help="check a file"
                       " directly instead of a config in a package")
    check.add_argument("--anbox", action="store_true", help="check"
                       " options needed for anbox too")
    check_package = check.add_argument("package", default="", nargs='?')
    if argcomplete:
        check_package.completer = kernel_completer

    # "pmbootstrap kconfig edit"
    edit = sub.add_parser("edit", help="edit kernel aport config")
    edit.add_argument("--arch", choices=arch_choices, dest="arch")
    edit.add_argument("-x", dest="xconfig", action="store_true",
                      help="use xconfig rather than ncurses for kernel"
                           " configuration")
    edit.add_argument("-g", dest="gconfig", action="store_true",
                      help="use gconfig rather than ncurses for kernel"
                           " configuration")
    edit_package = edit.add_argument("package")
    if argcomplete:
        edit_package.completer = kernel_completer


def arguments_repo_missing(subparser):
    ret = subparser.add_parser("repo_missing")
    package = ret.add_argument("package", nargs="?", help="only look at a"
                               " specific package and its dependencies")
    if argcomplete:
        package.completer = package_completer
    ret.add_argument("--arch", choices=pmb.config.build_device_architectures,
                     default=pmb.parse.arch.alpine_native())
    ret.add_argument("--built", action="store_true",
                     help="include packages which exist in the binary repos")
    ret.add_argument("--overview", action="store_true",
                     help="only print the pkgnames without any details")
    return ret


def arguments_lint(subparser):
    lint = subparser.add_parser("lint", help="run quality checks on pmaports"
                                             " (required to pass CI)")
    add_packages_arg(lint, nargs="*")


def arguments_status(subparser):
    ret = subparser.add_parser("status",
                               help="quick health check for the work dir")
    ret.add_argument("--details", action="store_true",
                     help="list passing checks in detail, not as summary")
    return ret


def package_completer(prefix, action, parser, parsed_args):
    args = parsed_args
    pmb.config.merge_with_args(args)
    pmb.helpers.args.replace_placeholders(args)
    pmb.helpers.args.add_cache(args)
    packages = set(
        package for package in pmb.helpers.pmaports.get_list(args)
        if package.startswith(prefix))
    return packages


def kernel_completer(prefix, action, parser, parsed_args):
    packages = package_completer("linux-" + prefix, action, parser, parsed_args)
    return [package.replace("linux-", "", 1) for package in packages]


def add_packages_arg(subparser, name="packages", *args, **kwargs):
    arg = subparser.add_argument(name, *args, **kwargs)
    if argcomplete:
        arg.completer = package_completer


def arguments():
    parser = argparse.ArgumentParser(prog="pmbootstrap")
    arch_native = pmb.parse.arch.alpine_native()
    arch_choices = set(pmb.config.build_device_architectures + [arch_native])
    mirrors_pmos_default = pmb.config.defaults["mirrors_postmarketos"]

    # Other
    parser.add_argument("-V", "--version", action="version",
                        version=pmb.config.version)
    parser.add_argument("-c", "--config", dest="config",
                        default=pmb.config.defaults["config"],
                        help="path to pmbootstrap.cfg file (default in"
                             " ~/.config/)")
    parser.add_argument("--config-channels",
                        help="path to channels.cfg (which is by default"
                             " read from pmaports.git, origin/master branch)")
    parser.add_argument("-d", "--port-distccd", dest="port_distccd")
    parser.add_argument("-mp", "--mirror-pmOS", dest="mirrors_postmarketos",
                        help="postmarketOS mirror, disable with: -mp='',"
                             " specify multiple with: -mp='one' -mp='two',"
                             " default: " + ", ".join(mirrors_pmos_default),
                        metavar="URL", action="append", default=[])
    parser.add_argument("-m", "--mirror-alpine", dest="mirror_alpine",
                        help="Alpine Linux mirror, default: " +
                             pmb.config.defaults["mirror_alpine"],
                        metavar="URL")
    parser.add_argument("-j", "--jobs", help="parallel jobs when compiling")
    parser.add_argument("-B", "--boot-size",
                        help="specify an integer with your preferred boot"
                             "partition size on target machine in MB (default"
                             " 128)")
    parser.add_argument("-p", "--aports",
                        help="postmarketos aports (pmaports) path")
    parser.add_argument("-t", "--timeout", help="seconds after which processes"
                        " get killed that stopped writing any output (default:"
                        " 900)", default=900, type=float)
    parser.add_argument("-w", "--work", help="folder where all data"
                        " gets stored (chroots, caches, built packages)")
    parser.add_argument("-y", "--assume-yes", help="Assume 'yes' to all"
                        " question prompts. WARNING: this option will"
                        " cause normal 'are you sure?' prompts to be"
                        " disabled!",
                        action="store_true")
    parser.add_argument("--as-root", help="Allow running as root (not"
                        " recommended, may screw up your work folders"
                        " directory permissions!)", dest="as_root",
                        action="store_true")
    parser.add_argument("-o", "--offline", help="Do not attempt to update"
                        " the package index files", action="store_true")

    # Compiler
    parser.add_argument("--no-ccache", action="store_false",
                        dest="ccache", help="do not cache the compiled output")
    parser.add_argument("--no-crossdirect", action="store_true",
                        help="Don't use the new, faster 'crossdirect' method,"
                             " use the old 'distcc-sshd' method instead. Use"
                             " if crossdirect broke something. This option"
                             " and the legacy 'distcc-sshd' code will be"
                             " removed soon if no problems turn up.")
    parser.add_argument("--distcc-nofallback", action="store_false",
                        help="when using the cross compiler via distcc fails,"
                             "do not fall back to compiling slowly with QEMU",
                        dest="distcc_fallback")
    parser.add_argument("--no-cross", action="store_false", dest="cross",
                        help="disable cross compiler, build only with QEMU and"
                             " gcc (slow!)")

    # Logging
    parser.add_argument("-l", "--log", dest="log", default=None,
                        help="path to log file")
    parser.add_argument("--details-to-stdout", dest="details_to_stdout",
                        help="print details (e.g. build output) to stdout,"
                             " instead of writing to the log",
                        action="store_true")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", help="write even more to the"
                        " logfiles (this may reduce performance)")
    parser.add_argument("-q", "--quiet", dest="quiet",
                        action="store_true", help="do not output any log messages")

    # Actions
    sub = parser.add_subparsers(title="action", dest="action")
    sub.add_parser("init", help="initialize config file")
    sub.add_parser("shutdown", help="umount, unregister binfmt")
    sub.add_parser("index", help="re-index all repositories with custom built"
                   " packages (do this after manually removing package files)")
    sub.add_parser("work_migrate", help="run this before using pmbootstrap"
                                        " non-interactively to migrate the"
                                        " work folder version on demand")
    arguments_repo_missing(sub)
    arguments_kconfig(sub)
    arguments_export(sub)
    arguments_flasher(sub)
    arguments_initfs(sub)
    arguments_qemu(sub)
    arguments_pkgrel_bump(sub)
    arguments_aportupgrade(sub)
    arguments_newapkbuild(sub)
    arguments_lint(sub)
    arguments_status(sub)

    # Action: log
    log = sub.add_parser("log", help="follow the pmbootstrap logfile")
    log_distccd = sub.add_parser(
        "log_distccd",
        help="follow the distccd logfile")
    for action in [log, log_distccd]:
        action.add_argument("-n", "--lines", default="60",
                            help="count of initial output lines")
        action.add_argument("-c", "--clear", help="clear the log",
                            action="store_true", dest="clear_log")

    # Action: zap
    zap = sub.add_parser("zap", help="safely delete chroot folders")
    zap.add_argument("--dry", action="store_true", help="instead of actually"
                     " deleting anything, print out what would have been"
                     " deleted")
    zap.add_argument("-hc", "--http", action="store_true", help="also delete http"
                     " cache")
    zap.add_argument("-d", "--distfiles", action="store_true", help="also delete"
                     " downloaded source tarballs")
    zap.add_argument("-p", "--pkgs-local", action="store_true",
                     dest="pkgs_local",
                     help="also delete *all* locally compiled packages")
    zap.add_argument("-m", "--pkgs-local-mismatch", action="store_true",
                     dest="pkgs_local_mismatch",
                     help="also delete locally compiled packages without"
                     " existing aport of same version")
    zap.add_argument("-o", "--pkgs-online-mismatch", action="store_true",
                     dest="pkgs_online_mismatch",
                     help="also delete outdated packages from online mirrors"
                     " (that have been downloaded to the apk cache)")
    zap.add_argument("-r", "--rust", action="store_true",
                     help="also delete rust related caches")

    # Action: stats
    stats = sub.add_parser("stats", help="show ccache stats")
    stats.add_argument("--arch", default=arch_native, choices=arch_choices)

    # Action: update
    update = sub.add_parser("update", help="update all existing APKINDEX"
                            " files")
    update.add_argument("--arch", default=None, choices=arch_choices,
                        help="only update a specific architecture")
    update.add_argument("--non-existing", action="store_true", help="do not"
                        " only update the existing APKINDEX files, but all of"
                        " them", dest="non_existing")

    # Action: build_init / chroot
    build_init = sub.add_parser("build_init", help="initialize build"
                                " environment (usually you do not need to call this)")
    chroot = sub.add_parser("chroot", help="start shell in chroot")
    chroot.add_argument("--add", help="build/install comma separated list of"
                        " packages in the chroot before entering it")
    chroot.add_argument("--user", help="run the command as user, not as root",
                        action="store_true")
    chroot.add_argument("--output", choices=["log", "stdout", "interactive",
                        "tui", "background"], help="how the output of the"
                        " program should be handled, choose from: 'log',"
                        " 'stdout', 'interactive', 'tui' (default),"
                        " 'background'. Details: pmb/helpers/run_core.py",
                        default="tui")
    chroot.add_argument("command", default=["sh", "-i"], help="command"
                        " to execute inside the chroot. default: sh", nargs='*')
    chroot.add_argument("-x", "--xauth", action="store_true",
                        help="Copy .Xauthority and set environment variables,"
                             " so X11 applications can be started (native"
                             " chroot only)")
    chroot.add_argument("-i", "--install-blockdev", action="store_true",
                        help="Create a sparse image file and mount it as"
                              " /dev/install, just like during the"
                              " installation process.")
    for action in [build_init, chroot]:
        suffix = action.add_mutually_exclusive_group()
        if action == chroot:
            suffix.add_argument("-r", "--rootfs", action="store_true",
                                help="Chroot for the device root file system")
        suffix.add_argument("-b", "--buildroot", nargs="?", const="device",
                            choices={"device"} | arch_choices,
                            help="Chroot for building packages, defaults to device "
                                 "architecture")
        suffix.add_argument("-s", "--suffix", default=None,
                            help="Specify any chroot suffix, defaults to"
                                 " 'native'")

    # Action: install
    install = sub.add_parser("install", help="set up device specific" +
                             " chroot and install to sdcard or image file")
    group = install.add_mutually_exclusive_group()
    group.add_argument("--sdcard", help="path to the sdcard device,"
                       " eg. /dev/mmcblk0")
    group.add_argument("--split", help="install the boot and root partition"
                       " in separated image files (default: only if flash method"
                       " requires it)", action="store_true", default=None)
    group.add_argument("--no-split", help="create combined boot + root image"
                       " even if flash method requires it",
                       dest="split", action="store_false")
    group.add_argument("--android-recovery-zip",
                       help="generate TWRP flashable zip",
                       action="store_true", dest="android_recovery_zip")
    group.add_argument("--no-image", help="do not generate the image",
                       action="store_true", dest="no_image")
    install.add_argument("--rsync", help="update the sdcard using rsync,"
                         " does not work with --fde", action="store_true")
    install.add_argument("--cipher", help="cryptsetup cipher used to"
                         " encrypt the rootfs, eg. aes-xts-plain64")
    install.add_argument("--iter-time", help="cryptsetup iteration time (in"
                         " milliseconds) to use when encrypting the system"
                         " partition")
    install.add_argument("--add", help="comma separated list of packages to be"
                         " added to the rootfs (e.g. 'vim,gcc')")
    install.add_argument("--no-fde", help=argparse.SUPPRESS,
                         action="store_true", dest="no_fde")
    install.add_argument("--fde", help="use full disk encryption",
                         action="store_true", dest="full_disk_encryption")
    install.add_argument("--flavor",
                         help="Specify kernel flavor to include in recovery"
                              " flashable zip", default=None)
    install.add_argument("--recovery-install-partition", default="system",
                         help="partition to flash from recovery,"
                              " eg. external_sd",
                         dest="recovery_install_partition")
    install.add_argument("--recovery-no-kernel",
                         help="do not overwrite the existing kernel",
                         action="store_false", dest="recovery_flash_kernel")
    install.add_argument("--no-base",
                         help="do not install postmarketos-base (advanced)",
                         action="store_false", dest="install_base")
    install.add_argument("--on-device-installer", "--ondev",
                         action="store_true",
                         help="wrap the resulting image in a graphical"
                              " on-device installer, so the installation can"
                              " be customized after flashing")
    install.add_argument("--no-local-pkgs", dest="install_local_pkgs",
                         help="do not install locally compiled packages and"
                              " package signing keys", action="store_false")
    install.add_argument("--no-recommends", dest="install_recommends",
                         help="do not install packages listed in"
                              " _pmb_recommends of the UI pmaports",
                         action="store_false")
    group = install.add_mutually_exclusive_group()
    group.add_argument("--sparse", help="generate sparse image file"
                       " (even if unsupported by device)", default=None,
                       action="store_true")
    group.add_argument("--no-sparse", help="do not generate sparse image file"
                       " (even if supported by device)", dest="sparse",
                       action="store_false")

    # Action: checksum
    checksum = sub.add_parser("checksum", help="update aport checksums")
    checksum.add_argument("--verify", action="store_true", help="download"
                          " sources and verify that the checksums of the"
                          " APKBUILD match, instead of updating them")
    add_packages_arg(checksum, nargs="+")

    # Action: aportgen
    aportgen = sub.add_parser("aportgen", help="generate a postmarketOS"
                              " specific package build recipe (aport/APKBUILD)")
    aportgen.add_argument("--fork-alpine", help="fork the alpine upstream package",
                          action="store_true", dest="fork_alpine")
    add_packages_arg(aportgen, nargs="+")

    # Action: build
    build = sub.add_parser("build", help="create a package for a"
                           " specific architecture")
    build.add_argument("--arch", choices=arch_choices, default=None,
                       help="CPU architecture to build for (default: " +
                       arch_native + " or first available architecture in"
                       " APKBUILD)")
    build.add_argument("--force", action="store_true", help="even build if not"
                       " necessary")
    build.add_argument("--strict", action="store_true", help="(slower) zap and install only"
                       " required depends when building, to detect dependency errors")
    build.add_argument("--src", help="override source used to build the"
                       " package with a local folder (the APKBUILD must"
                       " expect the source to be in $builddir, so you might"
                       " need to adjust it)",
                       nargs=1)
    build.add_argument("-i", "--ignore-depends", action="store_true",
                       help="only build and install makedepends from an"
                       " APKBUILD, ignore the depends (old behavior). This is"
                       " faster for device packages for example, because then"
                       " you don't need to build and install the kernel. But it"
                       " is incompatible with how Alpine's abuild handles it.",
                       dest="ignore_depends")
    build.add_argument("-n", "--no-depends", action="store_true",
                       help="never build dependencies, abort instead",
                       dest="no_depends")
    build.add_argument("--envkernel", action="store_true",
                       help="Create an apk package from the build output of"
                       " a kernel compiled with envkernel.sh.")
    add_packages_arg(build, nargs="+")

    # Action: apkbuild_parse
    apkbuild_parse = sub.add_parser("apkbuild_parse")
    add_packages_arg(apkbuild_parse, nargs="*")

    # Action: apkindex_parse
    apkindex_parse = sub.add_parser("apkindex_parse")
    apkindex_parse.add_argument("apkindex_path")
    add_packages_arg(apkindex_parse, "package", nargs="?")

    # Action: config
    config = sub.add_parser("config",
                            help="get and set pmbootstrap options")
    config.add_argument("-r", "--reset", action="store_true",
                        help="Reset config options with the given name to it's default.")
    config.add_argument("name", nargs="?", help="variable name, one of: " +
                        ", ".join(sorted(pmb.config.config_keys)),
                        choices=pmb.config.config_keys, metavar="name")
    config.add_argument("value", nargs="?", help="set variable to value")

    # Action: bootimg_analyze
    bootimg_analyze = sub.add_parser("bootimg_analyze", help="Extract all the"
                                     " information from an existing boot.img")
    bootimg_analyze.add_argument("path", help="path to the boot.img")
    bootimg_analyze.add_argument("--force", "-f", action="store_true",
                                 help="force even if the file seems to be"
                                      " invalid")

    # Action: pull
    sub.add_parser("pull", help="update all git repositories that pmbootstrap"
                   " cloned (pmaports, etc.)")

    if argcomplete:
        argcomplete.autocomplete(parser, always_complete_options="long")

    # Parse and extend arguments (also backup unmodified result from argparse)
    args = parser.parse_args()
    setattr(args, "from_argparse", copy.deepcopy(args))
    setattr(args.from_argparse, "from_argparse", args.from_argparse)
    pmb.helpers.args.init(args)
    return args
