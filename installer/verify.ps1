<#
.SYNOPSIS
  Checks an installer on this machine without touching a real installation: silent install into a temporary folder (with the
  "start with Windows" task), selftest of the INSTALLED exe, silent uninstall, then checks nothing is left behind.
.EXAMPLE
  installer\verify.ps1 -Setup installer\Output\Ruby-Setup-1.0.0.exe
#>
param([Parameter(Mandatory)][string]$Setup)
$ErrorActionPreference = "Stop"
$Setup = (Resolve-Path $Setup).Path
$dir = Join-Path $env:TEMP "ruby-install-test"
$data = Join-Path $env:TEMP "ruby-install-test-data"
$run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$uninstall = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{1E28E4B2-7175-4D78-8CB2-967EA7BF8300}_is1"
$menu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
function Check($ok, $what) { if (-not $ok) { throw "FAILED: $what" } else { Write-Host "ok: $what" } }
Remove-Item $dir, $data -Recurse -Force -ErrorAction SilentlyContinue

$p = Start-Process $Setup -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=`"$dir`"", "/TASKS=startup" -Wait -PassThru
Check ($p.ExitCode -eq 0) "silent install (exit code $($p.ExitCode))"
Check (Test-Path "$dir\Ruby.exe") "Ruby.exe is installed"
Check (Test-Path "$dir\_internal") "the bundled libraries are installed"
Check (Test-Path $uninstall) "listed in Apps and features"
Check (Test-Path "$menu\Ruby.lnk") "Start menu shortcut"
$value = (Get-ItemProperty $run -Name Ruby -ErrorAction SilentlyContinue).Ruby
Check ($value -eq "`"$dir\Ruby.exe`"") "the startup task wrote the Run entry ($value)"

$env:RUBY_HOME = $data
$t = Start-Process "$dir\Ruby.exe" -ArgumentList "--selftest" -Wait -PassThru
Remove-Item Env:RUBY_HOME
Check ($t.ExitCode -eq 0) "selftest of the installed exe"

# the uninstaller copies itself to %TEMP% and returns at once: wait until the files are really gone
Start-Process "$dir\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait | Out-Null
for ($i = 0; $i -lt 90 -and (Test-Path $dir); $i++) { Start-Sleep 1 }
Check (-not (Test-Path $dir)) "uninstall removed the program folder"
Check (-not (Get-ItemProperty $run -Name Ruby -ErrorAction SilentlyContinue).Ruby) "uninstall removed the Run entry"
Check (-not (Test-Path $uninstall)) "no longer listed in Apps and features"
Check (-not (Test-Path "$menu\Ruby.lnk")) "Start menu shortcut removed"
Remove-Item $data -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "installer OK"
