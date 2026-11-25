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

!macro customInstall
  ${ifNot} ${isUpdated}
    !insertmacro pockpockRemoveCaches
  ${endIf}
!macroend
