$ErrorActionPreference = 'Stop'
python "$PSScriptRoot\backend-python\scripts\prepare_first_tenant_snapshot.py" @args
exit $LASTEXITCODE
