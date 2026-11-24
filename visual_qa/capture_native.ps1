# Capture an actual foreground WinForms client area on the Windows hosted runner.
# No private application, account, credentials or entire desktop are captured.
param([Parameter(Mandatory=$true)][string]$OutputDir)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class VisualQaNative {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
'@
[void][VisualQaNative]::SetProcessDPIAware()
[System.Windows.Forms.Application]::EnableVisualStyles()
[void][System.IO.Directory]::CreateDirectory($OutputDir)
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Public synthetic Windows visual QA'
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$form.ClientSize = New-Object System.Drawing.Size(800,480)
$form.BackColor = [System.Drawing.Color]::FromArgb(16,25,35)
$form.ForeColor = [System.Drawing.Color]::White
$form.TopMost = $true
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedSingle
$form.MaximizeBox = $false
$form.MinimizeBox = $false

function Add-Label([string]$Text,[int]$X,[int]$Y,[int]$W,[int]$H,[int]$Size,[System.Drawing.Color]$Color) {
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $Text
    $label.Location = New-Object System.Drawing.Point($X,$Y)
    $label.Size = New-Object System.Drawing.Size($W,$H)
    $label.Font = New-Object System.Drawing.Font('Segoe UI',$Size)
    $label.ForeColor = $Color
    $form.Controls.Add($label)
    return $label
}
$white = [System.Drawing.Color]::FromArgb(236,241,246)
$muted = [System.Drawing.Color]::FromArgb(150,176,200)
$green = [System.Drawing.Color]::FromArgb(126,226,188)
$null = Add-Label 'Native Windows rendering check' 28 30 740 50 23 $white
$null = Add-Label 'PUBLIC / SYNTHETIC ONLY' 28 88 740 30 12 $muted
$null = Add-Label '128.40' 28 150 350 80 39 $green
$null = Add-Label 'Fixed invented display value' 30 235 650 36 15 $muted
$button = New-Object System.Windows.Forms.Button
$button.Text = 'Run interaction check'
$button.Location = New-Object System.Drawing.Point(30,295)
$button.Size = New-Object System.Drawing.Size(250,45)
$button.BackColor = [System.Drawing.Color]::FromArgb(36,71,96)
$button.ForeColor = $white
$button.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$form.Controls.Add($button)
$status = Add-Label 'Ready' 30 356 700 40 17 $green
$button.Add_Click({ $status.Text = 'Interaction passed' })
$null = Add-Label 'Actual client-area screen capture, not the private product.' 28 427 745 30 11 $muted
# Corner sentinels allow rejecting black, clipped, obscured, or wrong-window captures.
$sentinel = New-Object System.Windows.Forms.Panel
$sentinel.Location = New-Object System.Drawing.Point(755,20)
$sentinel.Size = New-Object System.Drawing.Size(24,24)
$sentinel.BackColor = [System.Drawing.Color]::FromArgb(250,170,70)
$form.Controls.Add($sentinel)
$sentinel.BringToFront()
$sentinel2 = New-Object System.Windows.Forms.Panel
$sentinel2.Location = New-Object System.Drawing.Point(755,400)
$sentinel2.Size = New-Object System.Drawing.Size(24,24)
$sentinel2.BackColor = [System.Drawing.Color]::FromArgb(70,180,250)
$form.Controls.Add($sentinel2)
$sentinel2.BringToFront()
$bitmap = $null
$graphics = $null
try {
    $form.Show()
    $form.Activate()
    [void][VisualQaNative]::SetForegroundWindow($form.Handle)
    $button.PerformClick()
    for ($i=0; $i -lt 15; $i++) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 100
    }
    if ($status.Text -ne 'Interaction passed') { throw 'Synthetic interaction did not complete' }
    if (-not [VisualQaNative]::IsWindowVisible($form.Handle)) { throw 'Native window not visible' }
    if ([VisualQaNative]::GetForegroundWindow() -ne $form.Handle) { throw 'No foreground native window; refusing screen capture' }
    $origin = $form.PointToScreen([System.Drawing.Point]::Empty)
    $size = $form.ClientSize
    $bounds = New-Object System.Drawing.Rectangle($origin,$size)
    if (-not [System.Windows.Forms.Screen]::FromControl($form).Bounds.Contains($bounds)) { throw 'Window not fully on one screen' }
    $bitmap = New-Object System.Drawing.Bitmap($size.Width,$size.Height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($origin,[System.Drawing.Point]::Empty,$size,[System.Drawing.CopyPixelOperation]::SourceCopy)
    foreach ($check in @(@(765,30,250,170,70),@(765,410,70,180,250),@(5,5,16,25,35))) {
        $pixel = $bitmap.GetPixel($check[0],$check[1])
        if ([Math]::Abs([int]$pixel.R-$check[2]) -gt 4 -or [Math]::Abs([int]$pixel.G-$check[3]) -gt 4 -or [Math]::Abs([int]$pixel.B-$check[4]) -gt 4) {
            throw 'Actual screen pixels do not match the visible fixture; no screenshot returned'
        }
    }
    $bitmap.Save((Join-Path $OutputDir 'windows-native.png'),[System.Drawing.Imaging.ImageFormat]::Png)
    Write-Output ('VISUAL_NATIVE {"capture":"CopyFromScreen","foreground":true,"sentinels_verified":true,"width":'+$size.Width+',"height":'+$size.Height+'}')
} finally {
    if ($graphics) { $graphics.Dispose() }
    if ($bitmap) { $bitmap.Dispose() }
    $form.Close()
    $form.Dispose()
}
