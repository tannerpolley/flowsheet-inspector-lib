#################################################################################
# Process Optimization and Modeling for Minerals Sustainability (PrOMMiS) Copyright (c) 2023-2026
#
# “Process Optimization and Modeling for Minerals Sustainability (PrOMMiS)” was produced under the DOE
# Process Optimization and Modeling for Minerals Sustainability (“PrOMMiS”) initiative, and is
# copyrighted by the software owners: The Regents of the University of California, through Lawrence
# Berkeley National Laboratory, National Technology & Engineering Solutions of Sandia, LLC through
# Sandia National Laboratories, Carnegie Mellon University, University of Notre Dame, and West
# Virginia University Research Corporation.
#
# NOTICE. This Software was developed under funding from the U.S. Department of Energy and the
# U.S. Government consequently retains certain rights. As such, the U.S. Government has been granted
# for itself and others acting on its behalf a paid-up, nonexclusive, irrevocable, worldwide license
# in the Software to reproduce, distribute copies to the public, prepare derivative works, and perform
# publicly and display publicly, and to permit other to do so.
#
#################################################################################
"""
Tests for reportdb module
"""

import json
import pytest
from idaes_fi.structfs import reportdb


@pytest.fixture
def tmp_db_path(tmp_path):
    return tmp_path / "reportdb_test.db"


@pytest.fixture
def tmpdb(tmp_db_path):
    return reportdb.ReportDB(tmp_db_path)


@pytest.mark.unit
def test_db_version(tmpdb):
    # initialize database
    db = tmpdb
    db.create(exist_ok=False)
    # sanity-check that initial DB is ok
    db.test_connection()

    # add a fake report, which will be checked later
    report_data = {"Arthur Dent": "human", "Ford Prefect": "Betelgeusian"}
    db.add_report(report_data, name="db_test")

    # change minor version in DB
    update_statement = f"UPDATE {db.VERSION_TABLE} SET minor = ?"
    for new_ver in (db.MINOR_VERSION - 1, db.MINOR_VERSION + 1):
        with db._connect() as conn:
            conn.execute(update_statement, (new_ver,))
        # Additive reports remain readable in either minor-version direction.
        db.test_connection()

    # change major version expect failure
    new_ver = db.MAJOR_VERSION + 1
    update_statement = f"UPDATE {db.VERSION_TABLE} SET major = ?"
    with db._connect() as conn:
        conn.execute(update_statement, (new_ver,))
    with pytest.raises(reportdb.DBError):
        db.test_connection()

    # recreate table and check again
    db.create(drop=False, exist_ok=True)
    # check that, once again, ok
    db.test_connection()
    # also make sure data is intact
    stored_report = db.get_last_report(name="db_test")
    assert stored_report == report_data


@pytest.mark.unit
def test_set_target(tmpdb):
    # empty is error
    with pytest.raises(ValueError):
        tmpdb.set_target(**{})
    # try each column
    all_col = {}
    for tgtcol in tmpdb.RPT_TGT_COL:
        name = tgtcol[0]
        kw = {name: "value"}
        tmpdb.set_target(**kw)
        all_col.update(kw)
    # try all columns
    tmpdb.set_target(**all_col)
    # bad column
    with pytest.raises(KeyError):
        tmpdb.set_target(bad_column="value")


@pytest.mark.unit
def test_get_target(tmpdb):
    kw = {c[0]: "value" for c in tmpdb.RPT_TGT_COL}
    tmpdb.set_target(**kw)
    # change values in input keywords
    for c in tmpdb.RPT_TGT_COL:
        kw[c[0]] = "value1"
    # assure that value in tmpdb has not changed
    tgt = tmpdb.get_target()
    for c in tmpdb.RPT_TGT_COL:
        assert kw[c[0]] != tgt[c[0]]
        # modify value returned by get_target
        tgt[c[0]] = kw[c[0]]
    # assure that changes to get_target return value
    # are not in the object (i.e. it is a copy)
    tgt = tmpdb.get_target()
    for c in tmpdb.RPT_TGT_COL:
        assert kw[c[0]] != tgt[c[0]]


@pytest.mark.unit
def test_connect():
    bad_path = "/"
    db = reportdb.ReportDB(bad_path)
    with pytest.raises(reportdb.DBError):
        db.test_connection()


@pytest.mark.unit
def test_get_last_meta(tmpdb):
    tmpdb.create(exist_ok=False)
    # empty db returns  None
    assert tmpdb.get_last_meta() is None
    # add a fake record
    tags = "tag1 tag2"
    tmpdb.add_report({"name": "value"}, tags=tags)
    m = tmpdb.get_last_meta()
    assert m["tags"] == tags


@pytest.mark.unit
def test_create(tmpdb):
    tmpdb.create(exist_ok=False)


@pytest.mark.unit
def test_create_migrates_missing_status_columns(tmpdb):
    """A DB whose status table predates newer columns (e.g. `solve_ok`) must be
    forward-migrated by create(exist_ok=True), which runs on every open."""
    tmpdb.create(exist_ok=False)
    # simulate a status table created by an older schema, without solve_ok
    with tmpdb._connect() as conn:
        conn.execute(f"DROP TABLE {tmpdb.STAT_TABLE};")
        old_cols = ", ".join(
            f"{nm} {ty}" for nm, ty in tmpdb.STAT_COL if nm != "solve_ok"
        )
        conn.execute(f"CREATE TABLE {tmpdb.STAT_TABLE} ( {old_cols} );")
    # re-open path: must add the missing column...
    tmpdb.create(exist_ok=True)
    # ...so that inserts which include it succeed
    rowid = tmpdb.add_report({})
    tmpdb.add_status(rowid, step_name="solve_initial", solve_ok=False)


@pytest.mark.unit
def test_status(tmpdb):
    tmpdb.create(exist_ok=False)
    # add a fake record
    tags = "tag1 tag2"
    rowid = tmpdb.add_report({}, tags=tags)
    # add statii for a steps; solve_ok is NULL for non-solve steps and
    # True/False for solve steps depending on solver termination
    steplist = (
        (1, "build", None),
        (2, "initialize", None),
        (3, "solve_initial", True),
        (4, "solve_optimization", False),
    )
    for num, name, solve_ok in steplist:
        errcode = num % 2
        errmsg = "boom!" if errcode else ""
        tmpdb.add_status(
            rowid,
            step_num=num,
            step_name=name,
            errcode=errcode,
            errmsg=errmsg,
            solve_ok=solve_ok,
        )
    # update record with fake report
    fake_report = {"fake": "report"}
    tmpdb.add_report(fake_report, update_row_id=rowid)
    # check that there is 1 report with status for each step
    with tmpdb._connect() as conn:
        cur = conn.cursor()
        cur.execute(f"select id, report from {tmpdb.RPT_TABLE};")
        rows = list(cur.fetchall())
        assert len(rows) == 1
        db_report = json.loads(rows[0][1])
        assert db_report == fake_report
        rptid = rows[0][0]
        cur.execute(
            f"select step_num, step_name, errcode, errmsg, solve_ok "
            f"from {tmpdb.STAT_TABLE} where run_id = ?;",
            (rptid,),
        )
        rows = list(cur.fetchall())
        assert len(rows) == len(steplist)
        for i, (num, name, solve_ok) in enumerate(steplist):
            print(f"check row {i}: {rows[i]}")
            assert rows[i][0] == num
            assert rows[i][1] == name
            expect_errcode = num % 2
            assert rows[i][2] == expect_errcode
            expect_errmsg = "boom!" if expect_errcode else ""
            assert rows[i][3] == expect_errmsg
            # None stays NULL; booleans are stored as 0/1
            expect_solve_ok = None if solve_ok is None else int(solve_ok)
            assert rows[i][4] == expect_solve_ok
