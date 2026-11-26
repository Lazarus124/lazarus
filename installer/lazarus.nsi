; Instalador de Lazarus para Windows (por usuario, sin permisos de administrador).
; Se compila con installer/build.sh (makensis). Requiere ../build/stage con python/ y app/.

Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

!ifndef VERSION
  !define VERSION "0.1.0"
!endif
!ifndef PAYLOAD
  !define PAYLOAD "..\build\payload.zip"   ; zip con las carpetas python y app
!endif
!ifndef OUTFILE
  !define OUTFILE "..\dist\Lazarus-Setup-${VERSION}.exe"
!endif

Name "Lazarus"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\Lazarus"
InstallDirRegKey HKCU "Software\Lazarus" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
BrandingText "Lazarus ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "Lazarus"
VIAddVersionKey "FileDescription" "Instalador de Lazarus"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Proyecto AWS re/Start"

!define MUI_ICON "lazarus.ico"
!define MUI_UNICON "lazarus.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Instalar Lazarus ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "Lazarus busca vacantes, las compara con su CV y escribe cartas de presentación.$\r$\n$\r$\nLa instalación no necesita permisos de administrador. Incluye Python y todas las librerías.$\r$\n$\r$\nRequisito aparte: Claude Code instalado. El inicio de sesión se hace desde Lazarus.$\r$\n$\r$\nSi Lazarus está abierto, el instalador lo cierra."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchLazarus
!define MUI_FINISHPAGE_RUN_TEXT "Abrir Lazarus"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Spanish"

!macro STOP_LAZARUS
  DetailPrint "Cerrando Lazarus si está abierto..."
  nsExec::Exec `powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Get-Process python,pythonw -ErrorAction SilentlyContinue | Where-Object { $$_.Path -like '$INSTDIR\python\*' } | Stop-Process -Force"`
  Pop $1
  Sleep 1500
!macroend

Function LaunchLazarus
  Exec '"$INSTDIR\python\pythonw.exe" "$INSTDIR\app\launcher.py"'
FunctionEnd

Section "Lazarus" SecMain
  SectionIn RO
  !insertmacro STOP_LAZARUS
  ; Una actualización reemplaza el programa. Los datos del usuario (~/.lazarus) no se tocan.
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\python"
  SetOutPath "$INSTDIR"
  File "lazarus.ico"
  InitPluginsDir
  SetCompress off
  File "/oname=$PLUGINSDIR\payload.zip" "${PAYLOAD}"
  SetCompress auto

  DetailPrint "Extrayendo Python y la aplicación (puede tardar un minuto)..."
  ${DisableX64FSRedirection}
  ${If} ${FileExists} "$WINDIR\System32\tar.exe"
    nsExec::ExecToLog '"$WINDIR\System32\tar.exe" -xf "$PLUGINSDIR\payload.zip" -C "$INSTDIR"'
    Pop $0
    ${EnableX64FSRedirection}
  ${Else}
    ${EnableX64FSRedirection}
    DetailPrint "tar.exe no existe en este Windows. Uso Expand-Archive (más lento)..."
    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath \"$PLUGINSDIR\payload.zip\" -DestinationPath \"$INSTDIR\" -Force"'
    Pop $0
  ${EndIf}
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "No pude extraer todos los archivos (código $0).$\r$\n$\r$\nCierre Lazarus y cualquier ventana de Python, y ejecute el instalador otra vez."
    Abort
  ${EndIf}
  Delete "$PLUGINSDIR\payload.zip"
  ${IfNot} ${FileExists} "$INSTDIR\python\pythonw.exe"
  ${OrIfNot} ${FileExists} "$INSTDIR\app\launcher.py"
    MessageBox MB_ICONSTOP "No pude extraer los archivos de Lazarus (código $0)."
    Abort
  ${EndIf}

  CreateDirectory "$SMPROGRAMS\Lazarus"
  CreateShortcut "$SMPROGRAMS\Lazarus\Lazarus.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\app\launcher.py"' "$INSTDIR\lazarus.ico" 0 SW_SHOWNORMAL "" "Abrir Lazarus"
  CreateShortcut "$SMPROGRAMS\Lazarus\Desinstalar Lazarus.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\Lazarus.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\app\launcher.py"' "$INSTDIR\lazarus.ico" 0 SW_SHOWNORMAL "" "Abrir Lazarus"

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Lazarus" "InstallDir" "$INSTDIR"
  !define UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\Lazarus"
  WriteRegStr HKCU "${UNINST}" "DisplayName" "Lazarus"
  WriteRegStr HKCU "${UNINST}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST}" "Publisher" "Proyecto AWS re/Start"
  WriteRegStr HKCU "${UNINST}" "DisplayIcon" "$INSTDIR\lazarus.ico"
  WriteRegStr HKCU "${UNINST}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "${UNINST}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  !insertmacro STOP_LAZARUS
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\python"
  Delete "$INSTDIR\lazarus.ico"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\Lazarus\Lazarus.lnk"
  Delete "$SMPROGRAMS\Lazarus\Desinstalar Lazarus.lnk"
  RMDir "$SMPROGRAMS\Lazarus"
  Delete "$DESKTOP\Lazarus.lnk"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Lazarus"
  DeleteRegKey HKCU "Software\Lazarus"
  ; Los datos del usuario (%USERPROFILE%\.lazarus: base, claves cifradas y logs) se conservan.
SectionEnd
