<#
.SYNOPSIS
  Builds the Ruby installer: PyInstaller (dist\Ruby) -> selftest of the compiled exe -> Inno Setup.
.EXAMPLE
  installer\build.ps1 -Version 1.0.0
  Needs Inno Setup 6 (https://jrsoftware.org/isinfo.php) and the Python environment of the project (.venv, see README).
  Result: installer\Output\Ruby-Setup-<version>.exe
#>
param(
    [string]$Version = "0.0.0-dev",
    [string]$Python = "",
    [switch]$SkipPyInstaller   # reuse the existing dist\Ruby
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not $Python) {
    $Python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
}

if (-not $SkipPyInstaller) {
    & $Python -m PyInstaller ruby.spec --noconfirm
    if ($LASTEXITCODE) { throw "PyInstaller failed" }
}

# The exe has no console: Start-Process -Wait is the only way to really wait for it and read its exit code.
$data = Join-Path $env:TEMP "ruby-selftest-data"
Remove-Item $data -Recurse -Force -ErrorAction SilentlyContinue
$env:RUBY_HOME = $data
$test = Start-Process (Resolve-Path "dist\Ruby\Ruby.exe") -ArgumentList "--selftest" -Wait -PassThru
Remove-Item Env:RUBY_HOME
Get-Content "$data\selftest.txt"
if ($test.ExitCode) { throw "The compiled exe failed its selftest (see above)" }

$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    $iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $iscc) { throw "Inno Setup 6 not found (https://jrsoftware.org/isdl.php)" }
& $iscc "/DAppVersion=$Version" "installer\ruby.iss"
if ($LASTEXITCODE) { throw "Inno Setup failed" }
Get-ChildItem "installer\Output\Ruby-Setup-$Version.exe" | Select-Object Name, @{n = "MB"; e = { [int]($_.Length / 1MB) } }
