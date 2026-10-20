# Idempotent Schema Helper Templates

Use one helper definition per migration, make all calls, then drop it. Replace example names and definitions with the migration's actual values.

## MySQL: add_column_if_not_exists

```sql
DROP PROCEDURE IF EXISTS `add_column_if_not_exists`;
DELIMITER $$
CREATE PROCEDURE `add_column_if_not_exists`(
  IN db_name_v varchar(64),
  IN table_name_v varchar(64),
  IN column_name_v varchar(64),
  IN column_definition_v varchar(1000)
)
BEGIN
  DECLARE column_exists int DEFAULT 0;

  SELECT COUNT(*) INTO column_exists
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = db_name_v
    AND TABLE_NAME = table_name_v
    AND COLUMN_NAME = column_name_v;

  IF column_exists = 0 THEN
    SET @ddl = CONCAT(
      'ALTER TABLE `', db_name_v, '`.`', table_name_v,
      '` ADD COLUMN ', column_definition_v
    );
    PREPARE stmt FROM @ddl;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END$$
DELIMITER ;

CALL `add_column_if_not_exists`(
  DATABASE(), 'example_table', 'new_column',
  '`new_column` varchar(64) DEFAULT NULL COMMENT ''示例字段'''
);

DROP PROCEDURE IF EXISTS `add_column_if_not_exists`;
```

Pass the column name explicitly. Do not infer it from a definition unless preserving an existing upstream helper verbatim.

## Kingbase: add_column_if_not_exists

Use the repository's Austin five-argument pattern. Keep `schema_name_v` as a function parameter and pass `current_schema()` at the call site.

```sql
DROP FUNCTION IF EXISTS add_column_if_not_exists(varchar, varchar, varchar, varchar, varchar);

CREATE OR REPLACE FUNCTION add_column_if_not_exists(
  schema_name_v varchar,
  table_name_v varchar,
  column_name_v varchar,
  column_definition_v varchar,
  column_comment_v varchar
) RETURNS void AS $$
DECLARE
  column_exists int;
BEGIN
  SELECT COUNT(*) INTO column_exists
  FROM information_schema.columns
  WHERE table_schema = schema_name_v
    AND table_name = table_name_v
    AND column_name = column_name_v;

  IF column_exists = 0 THEN
    EXECUTE format(
      'ALTER TABLE %I.%I ADD COLUMN %I %s',
      schema_name_v, table_name_v, column_name_v, column_definition_v
    );
  END IF;

  EXECUTE format(
    'COMMENT ON COLUMN %I.%I.%I IS %L',
    schema_name_v, table_name_v, column_name_v, column_comment_v
  );
END;
$$ LANGUAGE plpgsql;

SELECT add_column_if_not_exists(
  current_schema(),
  'example_table',
  'new_column',
  'varchar(64) DEFAULT NULL',
  '示例字段'
);

DROP FUNCTION IF EXISTS add_column_if_not_exists(varchar, varchar, varchar, varchar, varchar);
```

The comment is applied outside the existence branch so rerunning the migration also converges an outdated comment. Treat the type/default definition and comment as trusted migration constants.

## MySQL: modify_column_if_exists

```sql
DROP PROCEDURE IF EXISTS `modify_column_if_exists`;
DELIMITER $$
CREATE PROCEDURE `modify_column_if_exists`(
  IN db_name_v varchar(64),
  IN table_name_v varchar(64),
  IN column_name_v varchar(64),
  IN column_definition_v varchar(1000)
)
BEGIN
  DECLARE column_exists int DEFAULT 0;

  SELECT COUNT(*) INTO column_exists
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = db_name_v
    AND TABLE_NAME = table_name_v
    AND COLUMN_NAME = column_name_v;

  IF column_exists > 0 THEN
    SET @ddl = CONCAT(
      'ALTER TABLE `', db_name_v, '`.`', table_name_v,
      '` MODIFY COLUMN ', column_definition_v
    );
    PREPARE stmt FROM @ddl;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END$$
DELIMITER ;

CALL `modify_column_if_exists`(
  DATABASE(), 'example_table', 'score',
  '`score` decimal(10,3) DEFAULT NULL COMMENT ''评分'''
);

DROP PROCEDURE IF EXISTS `modify_column_if_exists`;
```

## Kingbase: modify_column_if_exists

Kingbase splits MySQL `MODIFY COLUMN` concerns. This helper changes only the type; handle default and nullability with separate guarded statements when required.

```sql
DROP FUNCTION IF EXISTS modify_column_if_exists(varchar, varchar, varchar, varchar);

CREATE OR REPLACE FUNCTION modify_column_if_exists(
  schema_name_v varchar,
  table_name_v varchar,
  column_name_v varchar,
  target_data_type_v varchar
) RETURNS void AS $$
DECLARE
  column_exists boolean;
BEGIN
  SELECT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = schema_name_v
      AND table_name = table_name_v
      AND column_name = column_name_v
  ) INTO column_exists;

  IF column_exists THEN
    EXECUTE format(
      'ALTER TABLE %I.%I ALTER COLUMN %I TYPE %s',
      schema_name_v, table_name_v, column_name_v, target_data_type_v
    );
  END IF;
END;
$$ LANGUAGE plpgsql;

SELECT modify_column_if_exists(
  current_schema(), 'example_table', 'score', 'decimal(10,3)'
);

DROP FUNCTION IF EXISTS modify_column_if_exists(varchar, varchar, varchar, varchar);
```

If conversion requires an expression, extend the helper with a trusted `USING` expression, for example `TYPE bigint USING column_name::bigint`. Never append MySQL `COMMENT`, `AFTER`, charset, or collation syntax to `target_data_type_v`.

## MySQL: add_index_if_not_exists

```sql
DROP PROCEDURE IF EXISTS `add_index_if_not_exists`;
DELIMITER $$
CREATE PROCEDURE `add_index_if_not_exists`(
  IN db_name_v varchar(64),
  IN table_name_v varchar(64),
  IN index_name_v varchar(64),
  IN column_list_v varchar(1000)
)
BEGIN
  DECLARE index_exists int DEFAULT 0;

  SELECT COUNT(*) INTO index_exists
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = db_name_v
    AND TABLE_NAME = table_name_v
    AND INDEX_NAME = index_name_v;

  IF index_exists = 0 THEN
    SET @ddl = CONCAT(
      'ALTER TABLE `', db_name_v, '`.`', table_name_v,
      '` ADD INDEX `', index_name_v, '` (', column_list_v, ')'
    );
    PREPARE stmt FROM @ddl;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END$$
DELIMITER ;

CALL `add_index_if_not_exists`(
  DATABASE(), 'example_table', 'idx_example_tenant',
  '`tenant_id`, `deleted_flag`'
);

DROP PROCEDURE IF EXISTS `add_index_if_not_exists`;
```

## Kingbase: add_index_if_not_exists

Keep `schema_name_v` as a function parameter and pass `current_schema()` at the call site:

```sql
DROP FUNCTION IF EXISTS add_index_if_not_exists(text, text, text, text, boolean);

CREATE OR REPLACE FUNCTION add_index_if_not_exists(
  schema_name_v text,
  table_name_v text,
  index_name_v text,
  column_list_v text,
  unique_v boolean DEFAULT false
) RETURNS void AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = schema_name_v
      AND tablename = table_name_v
      AND indexname = index_name_v
  ) THEN
    EXECUTE format(
      'CREATE %s INDEX %I ON %I.%I (%s)',
      CASE WHEN unique_v THEN 'UNIQUE' ELSE '' END,
      index_name_v, schema_name_v, table_name_v, column_list_v
    );
  END IF;
END;
$$ LANGUAGE plpgsql;

SELECT add_index_if_not_exists(
  current_schema(), 'example_table', 'idx_example_tenant',
  'tenant_id, deleted_flag', false
);

DROP FUNCTION IF EXISTS add_index_if_not_exists(text, text, text, text, boolean);
```

Treat `column_list_v` and type definitions as trusted migration constants, never user input.
