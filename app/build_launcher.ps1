# Builds Dugout.exe (the launcher) and the Desktop / Start menu shortcuts.
$ErrorActionPreference = 'Stop'
$app = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $app
& "$root\.venv\Scripts\python.exe" "$app\make_icon.py" | Out-Null
$csc = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$wv = "$app\webview2"           # WebView2 SDK (NuGet Microsoft.Web.WebView2): the app's own window
& $csc /nologo /target:winexe /platform:x64 /codepage:65001 "/win32icon:$app\Dugout.ico" "/out:$root\Dugout.exe" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll "/r:$wv\Microsoft.Web.WebView2.Core.dll" "/r:$wv\Microsoft.Web.WebView2.WinForms.dll" `
    "$app\DugoutLauncher.cs"
if ($LASTEXITCODE -ne 0) { throw 'csc failed' }
Copy-Item "$wv\*.dll" $root -Force         # next to Dugout.exe (the loader and the two .NET DLLs)
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $lnk = $shell.CreateShortcut((Join-Path $folder 'Dugout.lnk'))
    $lnk.TargetPath = "$root\Dugout.exe"
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = "$root\Dugout.exe,0"
    $lnk.Description = 'FL26 Dugout - Master League assistant'
    $lnk.Save()
}
"built $root\Dugout.exe"
