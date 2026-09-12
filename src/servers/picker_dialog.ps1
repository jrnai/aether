# Project Aether - Native PowerShell File and Folder Picker Dialog
# Ensures dialog opens TopMost in foreground above all other windows.
param(
    [string]$Type = "folder",
    [string]$Initial = "",
    [string]$Title = ""
)

[System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null
[System.Reflection.Assembly]::LoadWithPartialName("System.Drawing") | Out-Null

$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$owner.Size = New-Object System.Drawing.Size(1, 1)
$owner.Opacity = 0.01
$owner.ShowInTaskbar = $false
$owner.Show()
$owner.Activate()
$owner.BringToFront()

if ($Type -eq "folder") {
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    if ($Initial -and (Test-Path $Initial)) {
        $dialog.SelectedPath = $Initial
    }
    if ($Title) {
        $dialog.Description = $Title
    }
    $dialog.ShowNewFolderButton = $true
    $res = $dialog.ShowDialog($owner)
    if ($res -eq [System.Windows.Forms.DialogResult]::OK) {
        Write-Output $dialog.SelectedPath
    }
} else {
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    if ($Initial -and (Test-Path $Initial)) {
        $dialog.InitialDirectory = $Initial
    }
    if ($Title) {
        $dialog.Title = $Title
    }
    $dialog.Filter = "All Files (*.*)|*.*|Code Files (*.py;*.js;*.ts;*.html;*.css;*.json;*.yaml)|*.py;*.js;*.ts;*.html;*.css;*.json;*.yaml|Text Files (*.txt;*.md)|*.txt;*.md"
    $res = $dialog.ShowDialog($owner)
    if ($res -eq [System.Windows.Forms.DialogResult]::OK) {
        Write-Output $dialog.FileName
    }
}

$owner.Dispose()
