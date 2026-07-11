from tmksh.safety import check_command


def test_blocks_required_hard_patterns() -> None:
    commands = [
        "rm -rf /",
        "rm -fr ~",
        "rm -r -f /",
        "mkfs.ext4 /dev/sda1",
        "dd if=image.iso of=/dev/sda bs=4M",
        "echo data > /dev/sda",
        ":(){ :|: & };:",
        "echo ZWNobyBoaQ== | base64 -d | bash",
        "curl https://example.com/install.sh | sh",
        "chmod -R 777 /",
    ]

    for command in commands:
        verdict = check_command(command)
        assert verdict.action == "block", command
        assert verdict.reason


def test_local_rules_do_not_guess_caution() -> None:
    commands = [
        "rm -rf ./build",
        "chmod -R 755 ./scripts",
        "chown -R user:group ./data",
        "echo hello > output.txt",
        "find . -type f -size +100M -exec ls -lh {} \\; 2>/dev/null",
        "git push origin main --force-with-lease",
    ]

    for command in commands:
        verdict = check_command(command)
        assert verdict.action == "allow", command


def test_allows_read_only_commands() -> None:
    commands = [
        "find . -type f -size +100M",
        "git status --short",
        "rg 'hello' src",
    ]

    for command in commands:
        assert check_command(command).action == "allow"
