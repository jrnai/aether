' ==============================================================================
' Project Aether - Silent Desktop Application Launcher
' ==============================================================================
' Launches Project Aether backend silently via pythonw.exe (windowless Python)
' and opens the native standalone desktop app window without any terminal window.
' ==============================================================================

Option Explicit

Dim WshShell, fso, ScriptDir, RootDir, VenvPyw, Cmd

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

ScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
RootDir = fso.GetParentFolderName(ScriptDir)
WshShell.CurrentDirectory = RootDir

VenvPyw = RootDir & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(VenvPyw) Then
    VenvPyw = RootDir & "\.venv\Scripts\python.exe"
End If

Cmd = Chr(34) & VenvPyw & Chr(34) & " " & Chr(34) & RootDir & "\main.py" & Chr(34) & " --portal --open"

' 0 = Hide window (prevents any black console or command prompt from appearing)
WshShell.Run Cmd, 0, False
