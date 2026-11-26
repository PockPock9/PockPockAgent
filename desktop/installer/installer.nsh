; Included by electron-builder (package.json build.nsis.include).
;
; A manual install (the downloaded PockPock-Agent-Setup.exe) removes the old app's caches; an update
; installed from inside the app (electron-updater starts the installer with --updated) keeps them.
; Only caches are removed: chats, settings, keys, connectors, reports, logs, models and the Python
; environment are always kept. Keep the list in step with desktop/electron/fresh-install.cjs.

!macro pockpockRemoveCaches
  StrCpy $0 "$APPDATA\${PRODUCT_NAME}"
  RMDir /r "$0\Cache"
  RMDir /r "$0\Code Cache"
  RMDir /r "$0\GPUCache"
  RMDir /r "$0\DawnCache"
  RMDir /r "$0\DawnGraphiteCache"
  RMDir /r "$0\DawnWebGPUCache"
  RMDir /r "$0\GPUPersistentCache"
  RMDir /r "$0\GrShaderCache"
  RMDir /r "$0\ShaderCache"
  RMDir /r "$0\Shared Dictionary"
  RMDir /r "$0\Service Worker"
  RMDir /r "$0\blob_storage"
  RMDir /r "$0\Session Storage"
  ; Installers downloaded by the in-app updater (current and older app names).
  RMDir /r "$LOCALAPPDATA\pockpock-desktop-updater"
  RMDir /r "$LOCALAPPDATA\pockpock-ai-desktop-updater"
  ClearErrors
!macroend

; PockPock's background services (gateway, planner, validator, run store, browser automation, Local
; MCP) keep running after the app is closed. Their Python processes run from the Python runtime, not
; from the install folder, so electron-builder's "is the app running" check cannot see them, but their
; scripts and working folders are in $INSTDIR\resources\backend: Windows then refuses to replace those
; files and the installer stops with "PockPock Agent cannot be closed" (report 2026-11-26). Before
; installing by hand, stop every process whose command line names the install folder, with its child
; processes (some services start through a small launcher). Skipped: the app itself (the installer's
; own check closes it), this installer and its PowerShell. An in-app update already stops the services
; before it starts the installer (main.cjs beforeInstall), so this runs only for a manual install.
; The processes pockpockStopServices would stop: their number is the exit code (0 when none run).
!macro pockpockCountServices _RESULT
  nsExec::Exec `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$$me = (Get-CimInstance Win32_Process -Filter ('ProcessId=' + $$PID)).ParentProcessId; exit @(Get-CimInstance Win32_Process | Where-Object { $$_.CommandLine -and $$_.ProcessId -ne $$me -and $$_.ProcessId -ne $$PID -and $$_.Name -ne '${APP_EXECUTABLE_FILENAME}' -and $$_.CommandLine.IndexOf('$INSTDIR', [StringComparison]::OrdinalIgnoreCase) -ge 0 }).Count"`
  Pop ${_RESULT}
  ClearErrors
!macroend

!macro pockpockStopServices
  nsExec::Exec `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$$me = (Get-CimInstance Win32_Process -Filter ('ProcessId=' + $$PID)).ParentProcessId; Get-CimInstance Win32_Process | Where-Object { $$_.CommandLine -and $$_.ProcessId -ne $$me -and $$_.ProcessId -ne $$PID -and $$_.Name -ne '${APP_EXECUTABLE_FILENAME}' -and $$_.CommandLine.IndexOf('$INSTDIR', [StringComparison]::OrdinalIgnoreCase) -ge 0 } | ForEach-Object { & taskkill.exe /PID $$_.ProcessId /T /F | Out-Null }"`
  Pop $0
  ClearErrors
!macroend

; A manual install over an earlier one asks how to install (owner request 2026-11-26), when it finds
; PockPock's services running or the old app's caches:
;   Yes    = Repair: keep the caches, replace the app.
;   No     = Clean install: remove the caches (browser caches, old update downloads), install fresh.
;   Cancel = do not install.
; Both stop the old services first; chats, settings, keys, connectors, reports, logs, models and the
; Python environment are always kept. A silent install (/S) does a clean install, as before 0.2.13.
; Nothing is asked for a first install, or for an update installed from inside the app (--updated),
; which keeps the caches and has already stopped the services.
!macro customInit
  Var /GLOBAL pockpockClean
  StrCpy $pockpockClean "0"
  ${ifNot} ${isUpdated}
    StrCpy $pockpockClean "1"
    !insertmacro pockpockCountServices $R8
    StrCpy $R9 "0"
    IfFileExists "$APPDATA\${PRODUCT_NAME}\Cache\*.*" 0 +2
      StrCpy $R9 "1"
    IfFileExists "$APPDATA\${PRODUCT_NAME}\Code Cache\*.*" 0 +2
      StrCpy $R9 "1"
    IfFileExists "$LOCALAPPDATA\pockpock-desktop-updater\*.*" 0 +2
      StrCpy $R9 "1"
    StrCpy $R7 ""
    ${if} $R8 != "0"
    ${andIf} $R8 != "error"
      StrCpy $R7 " Its background services are running and will be stopped first."
    ${endIf}
    ${if} $R7 != ""
    ${orIf} $R9 == "1"
      MessageBox MB_YESNOCANCEL|MB_ICONQUESTION|MB_DEFBUTTON1 "PockPock Agent is already on this PC.$R7$\r$\n$\r$\nYes: Repair. Keep the caches and replace the app.$\r$\nNo: Clean install. Remove the caches (browser caches and old update downloads) and install fresh.$\r$\nCancel: do not install.$\r$\n$\r$\nYour chats, settings, keys and models are kept either way." /SD IDNO IDYES pockpockRepair IDNO pockpockClean
        Quit
      pockpockRepair:
        StrCpy $pockpockClean "0"
        Goto pockpockChosen
      pockpockClean:
        StrCpy $pockpockClean "1"
      pockpockChosen:
    ${endIf}
    !insertmacro pockpockStopServices
  ${endIf}
!macroend

!macro customInstall
  ${if} $pockpockClean == "1"
    !insertmacro pockpockRemoveCaches
  ${endIf}
!macroend
