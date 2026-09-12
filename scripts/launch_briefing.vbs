' Project Aether Silent Morning Briefing Launcher
' Executes launch_briefing.bat with a hidden window so no black console terminal pops up on Windows startup
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
ScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
RootDir = fso.GetParentFolderName(ScriptDir)
WshShell.CurrentDirectory = RootDir

BatPath = ScriptDir & "\launch_briefing.bat"
WshShell.Run chr(34) & BatPath & chr(34), 0, False
