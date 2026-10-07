$ErrorActionPreference = 'Stop'
$workspacePath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$toolDirectory = Join-Path $workspacePath '.cache\build-tools'
New-Item -ItemType Directory -Path $toolDirectory -Force | Out-Null
$installerPath = Join-Path $toolDirectory 'innosetup-6.7.3.exe'
Invoke-WebRequest -Uri 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe' -OutFile $installerPath
$signature = Get-AuthenticodeSignature -LiteralPath $installerPath
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Pyrsys B.V.') {
    throw 'Official Inno Setup signature verification failed'
}
$destinationPath = Join-Path $toolDirectory 'Inno'
$installationLog = Join-Path $toolDirectory 'install.log'
$arguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER',"/DIR=`"$destinationPath`"","/LOG=`"$installationLog`"")
$process = Start-Process -FilePath $installerPath -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Inno installation exit=$($process.ExitCode); log=$installationLog" }
Write-Output "Inno Setup ready: $destinationPath\ISCC.exe; log=$installationLog"
