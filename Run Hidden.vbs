Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.Run "pythonw server.py", 0, False
WScript.Sleep 1500
Set colFiles = GetObject("winmgmts:\\.\root\cimv2").ExecQuery("SELECT * FROM Win32_Process WHERE Name = 'pythonw.exe'")
If colFiles.Count > 0 Then
    MsgBox "Mobile Gamepad Server ejecutandose en segundo plano." & vbCrLf & vbCrLf & _
           "Abre en tu celular: http://" & GetIP() & ":5000" & vbCrLf & vbCrLf & _
           "Para detener: Abre el Administrador de Tareas y termina pythonw.exe", _
           vbInformation, "Mobile Gamepad"
End If

Function GetIP()
    On Error Resume Next
    Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")
    Set colItems = objWMIService.ExecQuery("SELECT IPAddress FROM Win32_NetworkAdapterConfiguration WHERE IPEnabled = True")
    For Each objItem in colItems
        If IsArray(objItem.IPAddress) Then
            For Each ip In objItem.IPAddress
                If Left(ip, 3) <> "127" And InStr(ip, ".") > 0 Then
                    GetIP = ip
                    Exit Function
                End If
            Next
        End If
    Next
    GetIP = "127.0.0.1"
End Function
