# Private persistent runtime directory

HACS preserves this directory across integration upgrades. Do not commit its
runtime contents. Embedded mode creates `uploads`, `extracted`, `runtime`,
`logs`, `state`, and `tmp` here. Uploaded application archives are mode 0600
and deleted after successful extraction by default. Extracted libraries are
mode 0500 and the user-supplied SDK key is mode 0600. Use the authenticated
Owlet Cam Reconfigure flow's separately confirmed delete action to remove all
proprietary material. Account passwords, Firebase tokens and camera KMS
credentials must never be stored here.
