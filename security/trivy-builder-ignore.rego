package trivy

default ignore = false

# Ubuntu's linux-libc-dev package contains exported userspace kernel headers.
# Trivy associates kernel implementation CVEs with that source package even
# though no kernel implementation is linked into or shipped with this app.
# The audit script expires this exception on 2026-12-01; review it sooner when
# the Ubuntu package, target release, or target architecture changes.
ignore {
    input.Type == "vulnerability"
    input.PkgName == "linux-libc-dev"
    input.InstalledVersion == "6.8.0-138.138"
    input.DataSource.ID == "ubuntu"
    startswith(input.Description, "In the Linux kernel, the following vulnerability has been resolved:")
    object.get(input, "FixedVersion", "") == ""
}

# Ubuntu also maps this Arm-processor hardware advisory to the amd64 header
# package. Keep the exception exact so any different advisory remains blocking.
ignore {
    input.Type == "vulnerability"
    input.VulnerabilityID == "CVE-2025-10263"
    input.PkgName == "linux-libc-dev"
    input.InstalledVersion == "6.8.0-138.138"
    input.PkgIdentifier.PURL == "pkg:deb/ubuntu/linux-libc-dev@6.8.0-138.138?arch=amd64&distro=ubuntu-24.04"
    input.DataSource.ID == "ubuntu"
    startswith(input.Description, "Arm C1-Ultra, C1-Premium")
    object.get(input, "FixedVersion", "") == ""
}
