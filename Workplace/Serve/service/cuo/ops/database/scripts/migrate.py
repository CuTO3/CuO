"""Run explicitly: python -m ops.database.scripts.migrate. Does not create roles or databases."""
import asyncio
from pathlib import Path
from psycopg import sql
from Core.settings import Settings
from Integration.postgresql import Database
async def migrate(db):
    template=(Path(__file__).resolve().parents[1]/"migrations/001_fuku.sql").read_text(encoding="utf-8")
    for gid in db.groups:
        schema=db.schemas[gid]
        async with db.transaction(gid) as tx:
            await tx.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
            marker=await (await tx.execute("SELECT obj_description(oid,'pg_namespace') AS version FROM pg_namespace WHERE nspname=%s",(schema,))).fetchone()
            if marker["version"] not in (None,"cuo-schema-v1","cuo-schema-v2"):
                raise RuntimeError("incompatible schema version")
            if marker["version"] is None:
                found=await (await tx.execute("SELECT count(*) AS n FROM pg_tables WHERE schemaname=%s",(schema,))).fetchone()
                if found["n"]: raise RuntimeError("nonempty unversioned schema; migrate manually")
                query=sql.SQL("").join([sql.SQL(piece) if i%2==0 else sql.Identifier(schema)
                    for i,piece in enumerate(sum(([piece,""] for piece in template.split("__SCHEMA__")[:-1]),[])+[template.split("__SCHEMA__")[-1]])])
                await tx.execute(query)
                await tx.execute(sql.SQL("COMMENT ON SCHEMA {} IS 'cuo-schema-v1'").format(sql.Identifier(schema)))
            if marker["version"] != "cuo-schema-v2":
                await tx.execute(sql.SQL("ALTER TABLE {}.divinations DROP CONSTRAINT IF EXISTS divinations_user_id_business_date_key").format(sql.Identifier(schema)))
                await tx.execute(sql.SQL("CREATE INDEX IF NOT EXISTS divinations_user_day_idx ON {}.divinations(user_id,business_date,created_at DESC)").format(sql.Identifier(schema)))
                await tx.execute(sql.SQL("CREATE UNIQUE INDEX IF NOT EXISTS divinations_pending_idx ON {}.divinations(user_id,business_date) WHERE status='generating'").format(sql.Identifier(schema)))
                await tx.execute(sql.SQL("COMMENT ON SCHEMA {} IS 'cuo-schema-v2'").format(sql.Identifier(schema)))
async def main():
    db=Database(Settings.load()); await db.open()
    try:
        check=await db.fetch(next(iter(db.groups)),"SELECT current_database() AS name")
        if check[0]["name"]!="CuO": raise RuntimeError('DATABASE_URL must select "CuO"')
        await migrate(db)
    finally: await db.close()
if __name__=="__main__":asyncio.run(main())
