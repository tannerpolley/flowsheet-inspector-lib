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
Simple database to contain reports for any number of flowsheets.
"""

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional

__author__ = "Dan Gunter (LBNL)"

_log = logging.getLogger(__name__)


class DBError(Exception):
    """General container for database exceptions"""

    def __init__(self, err: Exception):
        super().__init__(f"Error in database operation: {err}")


class ReportDB:
    """Store and retrieve flowsheet reports in a SQLite database.

    Each row stores report content together with target-identifying metadata
    such as flowsheet name, module, source filename, and user-defined tags.

    Args:
        filename: Path to the SQLite database file.
        **target_kw: Initial target metadata values keyed by names in
            :attr:`TARGET_COLUMNS`.

    Raises:
        KeyError: If any target keyword does not match a supported target
            column.
    """

    # for DB versioning
    # bump MINOR for backward-compatible schema changes (e.g. added tables or
    # columns), MAJOR for incompatible ones (dropped/retyped columns, changed
    # relationships)
    MAJOR_VERSION = 1
    MINOR_VERSION = 2  # 1.2: additive inputs and flowsheet_graph action reports
    VERSION_TABLE = "version"

    RPT_TABLE = "reports"
    RPT_TGT_COL = (
        ("name", "TEXT"),
        ("module", "TEXT"),
        ("filedir", "TEXT"),
        ("filename", "TEXT"),
        ("hash", "TEXT"),
    )
    RPT_COL = tuple(
        [
            ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
            ("created", "REAL"),
            ("tags", "TEXT"),
            ("solver_status", "TEXT"),
            ("run_status", "BOOLEAN"),
            ("run_exception", "TEXT"),
            ("report", "BLOB"),
        ]
        + list(RPT_TGT_COL)
    )
    STAT_TABLE = "status"
    STAT_COL = (
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("run_id", "INTEGER"),
        ("step_num", "INTEGER"),
        ("step_name", "TEXT"),
        ("start", "REAL"),
        ("duration", "REAL"),
        ("errcode", "INTEGER"),
        ("errmsg", "TEXT"),
        # Solver-quality flag, separate from the process status in `errcode`:
        # NULL = not a solve step (or termination status unknown),
        # 1 = solver terminated optimally, 0 = it did not (e.g. infeasible).
        ("solve_ok", "BOOLEAN"),
    )

    def __init__(self, filename: str, **target_kw):
        self._filename = filename
        self._tgtcol = [name for name, type_ in self.RPT_TGT_COL]
        self._tgtval = {k: "" for k in self._tgtcol}
        if target_kw:
            self.set_target(**target_kw)

    @property
    def filename(self) -> str:
        """Get current report filename."""
        return self._filename

    @property
    def version(self) -> tuple[int, int]:
        """Get major and minor version numbers

        Returns:
           major_version (int), minor_version (int)
        """
        with self._connect() as conn:
            return self._get_version(conn)

    def set_target(self, **kw):
        """Set default target metadata for future queries and inserts.

        Args:
            **kw: Target metadata values keyed by names in
                :attr:`TARGET_COLUMNS`.

        Raises:
            ValueError: If no keyword arguments are provided.
            KeyError: If a keyword does not match a supported target column.
        """
        if not kw:
            raise ValueError("At least one keyword argument required")
        for k, v in kw.items():
            k = k.lower()
            if k not in self._tgtcol:
                raise KeyError(f"Unknown target column '{k}'")
            self._tgtval[k] = v

    def get_target(self) -> dict:
        """Get (a copy of) the target keywords, as a dict {column: value}"""
        return self._tgtval.copy()

    @contextmanager
    def _connect(self):
        if _log.isEnabledFor(logging.DEBUG):
            _log.debug("Connecting to SQLite database: {self._filename}")
        try:
            conn = sqlite3.connect(self._filename)
        except sqlite3.OperationalError as err:
            _log.error(f"Cannot connect to report database '{self._filename}' ({err})")
            raise DBError(err)
        try:
            with conn:
                yield conn
        finally:
            conn.close()
            if _log.isEnabledFor(logging.DEBUG):
                _log.debug("Closed connection to SQLite database: {self._filename}")

    def test_connection(self) -> None:
        """Test database connection.

        This method will raise an exception of the DB connection
        is not valid, which includes a check of the version of the
        DB schema vs. the version of the code.

        Raises:
            DBError: If the database is unavailable or invalid
        """
        with self._connect() as conn:
            is_compatible, reason = self._check_compatible_version(conn)
        if not is_compatible:
            raise DBError(f"Database is not valid: {reason}")

    def _check_compatible_version(self, conn: sqlite3.Connection) -> tuple[bool, str]:
        major_version, minor_version = self._get_version(conn)
        # major versions must match
        if major_version != self.MAJOR_VERSION:
            return (
                False,
                f"Major version of database ({major_version}) != "
                f"major version of code ({self.MAJOR_VERSION})",
            )
        # minor versions do not have to match, but we may need to compensate
        if minor_version != self.MINOR_VERSION:
            _log.warning(
                f"Minor version in database ({minor_version}) "
                f"!= minor version of code ({self.MINOR_VERSION})"
            )
        return True, ""

    def _get_version(self, conn: sqlite3.Connection) -> tuple[int, int]:
        # get version in database
        query = f"SELECT * FROM {self.VERSION_TABLE}"
        try:
            # query the database using conn
            cursor = conn.execute(query)
        except sqlite3.OperationalError as err:
            raise DBError(f"Cannot get schema version: {err}")
        # get version data from results
        try:
            major_version, minor_version = cursor.fetchone()
        except sqlite3.OperationalError as err:
            raise DBError(f"Empty version table ({self.VERSION_TABLE})")
        return major_version, minor_version

    def create(self, drop=False, exist_ok=True) -> "ReportDB":
        """Create the reports & stats tables in the database.

        Args:
            drop: If ``True``, drop the existing reports table before creating
                it again.
            exist_ok: If `True` it is ok if the table exists

        Returns:
            self, for chaining

        Raises:
            sqlite3.Error: If SQLite cannot drop or create the table.
        """
        _log.info("Create reports table")
        with self._connect() as conn:
            # create new report and status tables
            if drop:
                conn.execute(f"DROP TABLE IF EXISTS {self.RPT_TABLE};")
                conn.execute(f"DROP TABLE IF EXISTS {self.STAT_TABLE};")
            rpt_cols = self._all_columns(typed=True)
            stat_cols = (f"{nm} {ty}" for nm, ty in self.STAT_COL)
            exists = "IF NOT EXISTS " if exist_ok else ""
            try:
                conn.execute(
                    f"CREATE TABLE {exists}{self.RPT_TABLE} ( {', '.join(rpt_cols)} );"
                )
            except sqlite3.OperationalError as err:
                # this may occur if the DB file is readonly, therefore fails on first write
                raise DBError(f"Cannot create table: {err}")
            conn.execute(
                f"CREATE TABLE {exists}{self.STAT_TABLE} ( {', '.join(stat_cols)} );"
            )
            # forward-migrate an existing status table: CREATE TABLE IF NOT
            # EXISTS does not add columns introduced after the table was made
            # (e.g. `solve_ok`), which would break later INSERTs
            existing_cols = {
                row[1] for row in conn.execute(f"PRAGMA table_info({self.STAT_TABLE});")
            }
            for nm, ty in self.STAT_COL:
                if nm not in existing_cols:
                    conn.execute(f"ALTER TABLE {self.STAT_TABLE} ADD COLUMN {nm} {ty};")
            # create new version table (always drop old)
            conn.execute(f"DROP TABLE IF EXISTS {self.VERSION_TABLE};")
            conn.execute(
                f"CREATE TABLE {self.VERSION_TABLE} (major integer, minor integer);"
            )
            # set current code version into table
            conn.execute(
                f"INSERT INTO {self.VERSION_TABLE} VALUES "
                f"({self.MAJOR_VERSION}, {self.MINOR_VERSION});"
            )
        return self

    def _all_columns(self, typed=False, exclude=None):
        result = []
        for nm, ty in self.RPT_COL:
            if exclude and nm in exclude:
                continue
            result.append(f"{nm} {ty}" if typed else nm)
        return result

    def add_report(
        self,
        data: str | dict,
        tags: str = "",
        run_status: bool = False,
        run_exc: str = "",
        solver_status: str = "NA",
        update_row_id: int = -1,
        **target_kw,
    ) -> int:
        """Insert a report and its metadata into the database.

        Args:
            data: Report payload as a JSON string or dictionary.
            tags: Space-separated tags to store with the report. Tags are
                normalized to lowercase and sorted before storage.
            run_status: Overall run success flag to store with the report.
            run_exc: Overall run exception message, if it failed.
            solver_status: Solver status value to store with the report.
            update_row_id: If 1 or greater, update a row with this id instead of adding new row
            **target_kw: Target metadata values for this report keyed by names
                in :attr:`TARGET_COLUMNS`. Values not provided here fall back
                to the current target set by :meth:`set_target`.

        Returns:
            id of newly created record

        Raises:
            KeyError: If required target metadata is missing from both
                ``target_kw`` and the current target defaults.
            TypeError: If ``data`` cannot be JSON-encoded when provided as a
                dictionary-like object.
            sqlite3.Error: If SQLite cannot insert the report.
        """
        _log.debug(f"Add a report, target={target_kw}")
        with self._connect() as conn:
            # set non-user column values
            created = time.time()
            insert_cols = self._all_columns(exclude=("id",))
            # sort tags so simple LIKE search can work
            tag_items = [t.lower() for t in tags.split()]
            tag_items.sort()
            tags = " ".join(tag_items)
            # get user-defined column values from 'kw'
            tgtvalues = [
                target_kw[u] if u in target_kw else self._tgtval[u]
                for u in self._tgtcol
            ]
            _log.debug(f"Add a report, target={tgtvalues} (cols={self._tgtcol})")
            # get report as bytes
            if isinstance(data, str):
                rpt_bytes = data.encode("utf-8")
            else:
                rpt_bytes = json.dumps(data).encode("utf-8")
            # construct inserted values and placeholder
            colvalues = [
                created,
                tags,
                solver_status,
                run_status,
                run_exc,
                rpt_bytes,
            ] + tgtvalues
            ph = ",".join("?" * len(insert_cols))
            # execute the insert
            cur = conn.cursor()
            if update_row_id < 1:
                insert_cols_str = ", ".join(insert_cols)
                stmt = (
                    f"INSERT INTO {self.RPT_TABLE} ({insert_cols_str}) VALUES ({ph});"
                )
            else:
                ph = ",".join((f"{col} = ?" for col in insert_cols))
                stmt = f"UPDATE {self.RPT_TABLE} SET {ph} WHERE id = {update_row_id}"

            last_id = -1
            try:
                cur.execute(stmt, colvalues)
                last_id = cur.lastrowid
            except sqlite3.OperationalError as err:
                raise DBError(err)
            finally:
                # cleanup
                cur.close()

        return last_id

    def add_status(
        self,
        run_id: int,
        step_num: int = 0,
        step_name: str = "",
        start: float = 0.0,
        duration: float = 0.0,
        errcode: int = 0,
        errmsg: str = "",
        solve_ok: Optional[bool] = None,
    ):
        """Add a new record for the status of an executed flowsheet step.

        Args:
            run_id: Report row this step status belongs to.
            step_num: Index of the step in the canonical step order.
            step_name: Name of the step.
            start: Step start time (Unix timestamp, seconds).
            duration: Step duration in seconds.
            errcode: Process status: 0 if the step ran without raising, 1 if
                it raised an exception.
            errmsg: Error message if the step failed, else empty string.
            solve_ok: Solver-quality status, independent of `errcode`:
                True/False if this was a solve step whose solver did/did not
                terminate optimally, None (stored as NULL) for non-solve steps
                or when the termination status is unknown.
        """
        with self._connect() as conn:
            last_id = -1
            insert_cols = [x[0] for x in self.STAT_COL[1:]]  # get names, skip 'id'
            colvalues = (
                run_id,
                step_num,
                step_name,
                start,
                duration,
                errcode,
                errmsg,
                solve_ok,
            )
            insert_cols_str = ",".join(insert_cols)
            ph = ",".join("?" * len(insert_cols))
            stmt = f"INSERT INTO {self.STAT_TABLE} ({insert_cols_str}) VALUES ({ph})"
            cur = conn.cursor()
            try:
                cur.execute(stmt, colvalues)
                last_id = cur.lastrowid
            except sqlite3.OperationalError as err:
                raise DBError(err)
            finally:
                # cleanup
                cur.close()

        return last_id

    def get_metadata(self, tags: str = "", **target_kw):
        """Yield metadata rows for reports matching the provided filters.

        Args:
            tags: Space-separated tags that must all be present in a matching
                report.
            **target_kw: Target metadata filters keyed by names in
                :attr:`TARGET_COLUMNS`. Values not provided here fall back to
                the current target defaults.

        Yields:
            tuple: Report metadata rows excluding the report payload itself.

        Raises:
            sqlite3.Error: If SQLite cannot execute the query.
        """
        columns = ", ".join(self._all_columns(exclude=("report",)))
        stmt = f"SELECT {columns} from {self.RPT_TABLE}"
        stmt += self._where(target_kw, tags=tags)
        with self._connect() as conn:
            for row in conn.execute(stmt):
                yield row

    def get_report(self, index) -> str:
        """Read a report payload by database row identifier.

        Args:
            index: SQLite row identifier for the report to read.

        Returns:
            dict | list | str | int | float | bool | None: Parsed JSON content
            stored for the report.

        Raises:
            sqlite3.Error: If SQLite cannot read the report blob.
            json.JSONDecodeError: If the stored payload is not valid JSON.
        """
        with self._connect() as conn:
            with conn.blobopen(self.RPT_TABLE, "report", index) as blob:
                data = blob.read()
        return json.loads(data.decode("utf-8"))

    def get_last_meta(self, **kwargs) -> dict | None:
        """Return the newest report matching the provided filters.

        Examples:
            ``db.get_last_meta(name="test_1")``
            ``db.get_last_meta(name="hda", tags="test Monday")``
            ``db.get_last_meta(module="my.cool.flowsheet")``

        Args:
            **kwargs: Target metadata filters keyed by names in
                :attr:`TARGET_COLUMNS`, plus the optional ``tags`` keyword. If
                ``tags`` is provided, its value must be a string of
                space-separated tags that must all be present in the report.

        Returns:
            dict | None: The newest matching metadata fields, or ``None`` if no report
            matches the filters.

        Raises:
            sqlite3.Error: If SQLite cannot execute the query or read the
                report blob.
            json.JSONDecodeError: If the stored payload is not valid JSON.
        """
        # Extract 'tags' from kwargs (may be None)
        # (Don't put tags=None in function signature, otherwise it
        # will confusingly be a positional argument as well)
        tags = kwargs.pop("tags", None)

        column_list = self._all_columns(exclude=("id", "report"))
        columns = ", ".join(column_list)

        # connect to db
        with self._connect() as conn:
            # build query
            stmt = f"SELECT {columns} FROM {self.RPT_TABLE}"
            stmt += self._where(kwargs, tags=tags)
            # run query
            row = conn.execute(stmt).fetchone()
            # if none, done; else read the report
            if row is None:
                return None  # RETURN!

        row_dict = {}
        for i, col in enumerate(column_list):
            row_dict[col] = row[i]

        return row_dict

    def get_last_report(self, **kwargs) -> dict | None:
        """Return the newest metadata fields matching the provided filters.

        Examples:
            ``db.get_last_report(name="test_1")``
            ``db.get_last_report(name="hda", tags="test Monday")``
            ``db.get_last_report(module="my.cool.flowsheet")``

        Args:
            **kwargs: Target metadata filters keyed by names in
                :attr:`TARGET_COLUMNS`, plus the optional ``tags`` keyword. If
                ``tags`` is provided, its value must be a string of
                space-separated tags that must all be present in the report.

        Returns:
            dict | None: The newest matching report, or ``None`` if no report
            matches the filters.

        Raises:
            sqlite3.Error: If SQLite cannot execute the query or read the
                report blob.
            json.JSONDecodeError: If the stored payload is not valid JSON.
        """
        # Extract 'tags' from kwargs (may be None)
        # (Don't put tags=None in function signature, otherwise it
        # will confusingly be a positional argument as well)
        tags = kwargs.pop("tags", None)

        # connect to db
        with self._connect() as conn:
            # build query
            stmt = f"SELECT MAX(id) FROM {self.RPT_TABLE}"
            stmt += self._where(kwargs, tags=tags)
            # run query
            try:
                index = conn.execute(stmt).fetchone()[0]
            except sqlite3.OperationalError as err:
                raise DBError(err)
            # if none, done; else read the report
            if index is None:
                return None  # RETURN!
            with conn.blobopen(self.RPT_TABLE, "report", int(index)) as blob:
                data = blob.read()

        # parse report into dict before returning it
        return json.loads(data.decode("utf-8"))

    def _where(self, fltr, tags=None):
        expr = []
        for col in self._tgtcol:
            if col in fltr:
                expr.append(f"{col} = '{fltr[col]}'")
            elif self._tgtval[col]:
                expr.append(f"{col} = '{self._tgtval[col]}'")
        if tags:
            tag_items = [t.lower() for t in tags.split()]
            tag_items.sort()
            pattern = "%" + "%".join(tag_items) + "%"
            expr.append(f"tags LIKE '{pattern}'")
        if expr:
            conj = " AND ".join(expr)
            clause = f" WHERE {conj}"
        else:
            clause = ""  # nothing at all
        return clause
