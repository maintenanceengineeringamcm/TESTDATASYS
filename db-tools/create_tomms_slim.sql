/* ==========================================================================
   Build Tomms_CEBT_HI - the small copy of the Tomms CMMS the HI system needs
   ==========================================================================

   The HI system reads only three of Tomms_CEBT's 387 tables:

     ast_mst   asset number, short description, status  -> navigator names,
                                                          "in service" filter
     ast_det   ast_det_datetime1 / ast_det_datetime6     -> year of manufacture
                                                          (the AGE criterion)
     cf_label  captions of those ast_det columns

   Together about 216 MB of a 66 GB database - the rest is mostly document and
   attachment stores (ast_ref 38 GB, wko_ref 19 GB) the system never touches.

   This script copies the three tables, whole and under their original names,
   into a new database, indexes them, and backs it up. The application needs no
   code change: point HI_TOMMS_DB_NAME at the new database.

   SAFE TO RE-RUN. The source is only read. The target database is dropped and
   rebuilt each time, so re-running it is how you refresh the copy.

   HOW TO RUN - on the SQL Server instance that holds Tomms_CEBT:
     * double-click create_tomms_slim.bat (edit the server name in it first), or
     * open this file in SSMS and press Execute (F5).
   Needs sysadmin, or CREATE DATABASE plus db_backupoperator.
   ========================================================================== */

SET NOCOUNT ON;
SET XACT_ABORT ON;

-- ------------------------------------------------------------ settings -----
DECLARE @SourceDb   sysname        = N'Tomms_CEBT';
DECLARE @TargetDb   sysname        = N'Tomms_CEBT_HI';
DECLARE @SiteCd     varchar(10)    = 'CEBT';   -- the CMMS site the HI system uses
-- Folder for the .bak, as seen by the SQL Server machine. The .bat fills this
-- in (its own backup\ folder). Run from SSMS it stays blank and the instance's
-- default backup folder is used - which only the SQL Server service can read,
-- so put a folder you can open here, e.g. N'D:\HI_Backup' (the SQL Server
-- service account needs write access to it).
DECLARE @BackupDir  nvarchar(400)  = N'$(BackupDir)';
-- Still the literal placeholder (run from SSMS) or blank -> default folder.
IF @BackupDir = N'' OR LEFT(@BackupDir, 1) = N'$' SET @BackupDir = NULL;
-- ---------------------------------------------------------------------------

DECLARE @started datetime2 = SYSDATETIME();
DECLARE @sql nvarchar(max), @src nvarchar(300), @tgt nvarchar(300), @n bigint, @msg nvarchar(400);

IF DB_ID(@SourceDb) IS NULL
BEGIN
    RAISERROR(N'Source database %s not found on this instance.', 16, 1, @SourceDb);
    RETURN;
END;
IF @TargetDb = @SourceDb
BEGIN
    RAISERROR(N'@TargetDb must differ from @SourceDb - the target is dropped.', 16, 1);
    RETURN;
END;

SET @src = QUOTENAME(@SourceDb) + N'.dbo.';
SET @tgt = QUOTENAME(@TargetDb) + N'.dbo.';

-- 1. Fresh, empty target --------------------------------------------------
IF DB_ID(@TargetDb) IS NOT NULL
BEGIN
    RAISERROR(N'Step 1/5: Dropping the previous %s ...', 0, 1, @TargetDb) WITH NOWAIT;
    SET @sql = N'ALTER DATABASE ' + QUOTENAME(@TargetDb) + N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; '
             + N'DROP DATABASE ' + QUOTENAME(@TargetDb) + N';';
    EXEC (@sql);
END;
RAISERROR(N'Step 1/5: Creating %s ...', 0, 1, @TargetDb) WITH NOWAIT;
SET @sql = N'CREATE DATABASE ' + QUOTENAME(@TargetDb) + N'; '
         + N'ALTER DATABASE ' + QUOTENAME(@TargetDb) + N' SET RECOVERY SIMPLE;';
EXEC (@sql);

-- 2. Copy the three tables (all columns, so later features can use them) ---
RAISERROR(N'Step 2/5: Copying ast_mst ...', 0, 1) WITH NOWAIT;
SET @sql = N'SELECT * INTO ' + @tgt + N'ast_mst FROM ' + @src + N'ast_mst WHERE site_cd = @site;';
EXEC sp_executesql @sql, N'@site varchar(10)', @site = @SiteCd;

-- ast_det rows belong to an ast_mst row; keep only those of the copied assets.
RAISERROR(N'Step 2/5: Copying ast_det ...', 0, 1) WITH NOWAIT;
SET @sql = N'SELECT d.* INTO ' + @tgt + N'ast_det FROM ' + @src + N'ast_det d '
         + N'WHERE EXISTS (SELECT 1 FROM ' + @tgt + N'ast_mst m WHERE m.RowID = d.mst_RowID);';
EXEC (@sql);

RAISERROR(N'Step 2/5: Copying cf_label ...', 0, 1) WITH NOWAIT;
SET @sql = N'SELECT * INTO ' + @tgt + N'cf_label FROM ' + @src + N'cf_label;';
EXEC (@sql);

-- 3. Indexes - the source tables are unindexed heaps, which is why the
--    manufacture-year pull took ~4 minutes there. -------------------------
RAISERROR(N'Step 3/5: Indexing ...', 0, 1) WITH NOWAIT;
SET @sql = N'USE ' + QUOTENAME(@TargetDb) + N';
CREATE UNIQUE CLUSTERED INDEX cx_ast_mst ON dbo.ast_mst (RowID);
CREATE INDEX ix_ast_mst_asset ON dbo.ast_mst (site_cd, ast_mst_asset_no)
    INCLUDE (ast_mst_asset_shortdesc, ast_mst_asset_status);
CREATE CLUSTERED INDEX cx_ast_det ON dbo.ast_det (mst_RowID);
CREATE CLUSTERED INDEX cx_cf_label ON dbo.cf_label (table_name, language_cd, column_name);';
EXEC (@sql);

-- 4. Check the copy is complete --------------------------------------------
RAISERROR(N'Step 4/5: Verifying ...', 0, 1) WITH NOWAIT;
DECLARE @check TABLE (tbl sysname, source_rows bigint, copied_rows bigint);
SET @sql = N'SELECT ''ast_mst'', (SELECT COUNT_BIG(*) FROM ' + @src + N'ast_mst WHERE site_cd = @site), (SELECT COUNT_BIG(*) FROM ' + @tgt + N'ast_mst)
UNION ALL SELECT ''ast_det'', (SELECT COUNT_BIG(*) FROM ' + @src + N'ast_det d JOIN ' + @src + N'ast_mst m ON m.RowID = d.mst_RowID WHERE m.site_cd = @site), (SELECT COUNT_BIG(*) FROM ' + @tgt + N'ast_det)
UNION ALL SELECT ''cf_label'', (SELECT COUNT_BIG(*) FROM ' + @src + N'cf_label), (SELECT COUNT_BIG(*) FROM ' + @tgt + N'cf_label);';
INSERT @check EXEC sp_executesql @sql, N'@site varchar(10)', @site = @SiteCd;
SELECT tbl AS [table], source_rows, copied_rows,
       CASE WHEN source_rows = copied_rows THEN 'OK' ELSE 'MISMATCH' END AS [check]
FROM @check;
IF EXISTS (SELECT 1 FROM @check WHERE source_rows <> copied_rows)
BEGIN
    RAISERROR(N'Row counts differ - the copy is incomplete. Nothing was backed up.', 16, 1);
    RETURN;
END;

-- 5. Back it up -----------------------------------------------------------
IF @BackupDir IS NULL
    SET @BackupDir = CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(400));
DECLARE @file nvarchar(600) = @BackupDir
      + CASE WHEN RIGHT(@BackupDir, 1) IN (N'\', N'/') THEN N'' ELSE N'\' END
      + @TargetDb + N'.bak';
RAISERROR(N'Step 5/5: Backing up to %s ...', 0, 1, @file) WITH NOWAIT;

-- Express cannot compress backups; every other edition can.
IF CAST(SERVERPROPERTY('EngineEdition') AS int) = 4
    SET @sql = N'BACKUP DATABASE ' + QUOTENAME(@TargetDb) + N' TO DISK = @f WITH INIT, CHECKSUM;';
ELSE
    SET @sql = N'BACKUP DATABASE ' + QUOTENAME(@TargetDb) + N' TO DISK = @f WITH INIT, CHECKSUM, COMPRESSION;';
EXEC sp_executesql @sql, N'@f nvarchar(600)', @f = @file;

-- Summary ------------------------------------------------------------------
SET @sql = N'SELECT CAST(SUM(size) * 8 / 1024.0 AS decimal(10,1)) FROM ' + QUOTENAME(@TargetDb) + N'.sys.database_files WHERE type = 0';
DECLARE @mb TABLE (mb decimal(10,1));
INSERT @mb EXEC (@sql);
SELECT @TargetDb AS [database],
       (SELECT mb FROM @mb) AS database_mb,
       (SELECT TOP 1 CAST(compressed_backup_size / 1048576.0 AS decimal(10,1))
          FROM msdb.dbo.backupset WHERE database_name = @TargetDb
          ORDER BY backup_finish_date DESC) AS backup_mb,
       @file AS backup_file,
       DATEDIFF(SECOND, @started, SYSDATETIME()) AS seconds_taken;

SET @msg = N'Done. Copy ' + @file + N' to the Docker host backup folder and set HI_TOMMS_DB_NAME='
         + @TargetDb + N' in .env.';
RAISERROR(@msg, 0, 1) WITH NOWAIT;
