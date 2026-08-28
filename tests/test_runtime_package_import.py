from __future__ import annotations

import subprocess
import sys


def test_runtime_package_does_not_preimport_service_module():
    code = (
        "import sys; import caldav_assistant.internal.runtime; "
        "print(int('caldav_assistant.internal.runtime.service' in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "0"
