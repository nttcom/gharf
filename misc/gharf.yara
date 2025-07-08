rule Detect_GHARF_Artifact
{
    meta:
        description = "Rule to detect legacy artifact file created by GHARF"
        author = "ykubo"
        date = "2025/07/09"

    strings:
        $marker = "IOC-GHARF"

    condition:
        uint16(0) == 0x5A4D and $marker in (0..uint32(0x3C) - 1)
}
