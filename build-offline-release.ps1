$ErrorActionPreference = 'Stop'
python "$PSScriptRoot\backend-python\scripts\build_offline_release.py" @args
exit $LASTEXITCODE
