from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MONEY_QUANT = Decimal("0.01")


def _format_money(value: Decimal) -> str:
    return format(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP), "f")


def _month_bounds_utc(year: int, month: int, timezone_name: str) -> tuple[datetime, datetime]:
    try:
        property_timezone = ZoneInfo(timezone_name or "UTC")
    except ZoneInfoNotFoundError:
        property_timezone = ZoneInfo("UTC")

    start_local = datetime(year, month, 1, tzinfo=property_timezone)
    if month < 12:
        end_local = datetime(year, month + 1, 1, tzinfo=property_timezone)
    else:
        end_local = datetime(year + 1, 1, 1, tzinfo=property_timezone)

    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


async def calculate_monthly_revenue(
    property_id: str,
    tenant_id: str,
    month: int,
    year: int,
    db_session=None,
) -> Dict[str, Any]:
    """
    Calculates revenue for a specific property month in the property's timezone.
    """
    try:
        from sqlalchemy import text

        async def execute_monthly_query(session):
            timezone_query = text("""
                SELECT timezone
                FROM properties
                WHERE id = :property_id AND tenant_id = :tenant_id
                LIMIT 1
            """)
            timezone_result = await session.execute(timezone_query, {
                "property_id": property_id,
                "tenant_id": tenant_id,
            })
            timezone_row = timezone_result.fetchone()
            property_timezone = timezone_row.timezone if timezone_row and timezone_row.timezone else "UTC"
            start_date, end_date = _month_bounds_utc(year, month, property_timezone)

            print(f"DEBUG: Querying monthly revenue for {property_id}/{tenant_id} from {start_date} to {end_date}")

            query = text("""
                SELECT
                    COALESCE(SUM(total_amount), 0) as total_revenue,
                    COUNT(*) as reservation_count
                FROM reservations
                WHERE property_id = :property_id
                AND tenant_id = :tenant_id
                AND check_in_date >= :start_date
                AND check_in_date < :end_date
            """)

            result = await session.execute(query, {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
            })
            row = result.fetchone()
            total_revenue = Decimal(str(row.total_revenue if row else "0"))

            return {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "total": _format_money(total_revenue),
                "currency": "USD",
                "count": row.reservation_count if row else 0,
                "month": month,
                "year": year,
                "timezone": property_timezone,
            }

        if db_session is not None:
            return await execute_monthly_query(db_session)

        from app.core.database_pool import DatabasePool

        db_pool = DatabasePool()
        await db_pool.initialize()

        if db_pool.session_factory:
            async with db_pool.get_session() as session:
                return await execute_monthly_query(session)

        raise Exception("Database pool not available")

    except Exception as e:
        print(f"Database error for monthly revenue {property_id} (tenant: {tenant_id}): {e}")
        return {
            "property_id": property_id,
            "tenant_id": tenant_id,
            "total": "0.00",
            "currency": "USD",
            "count": 0,
            "month": month,
            "year": year,
            "timezone": "UTC",
        }

async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates revenue from database.
    """
    try:
        # Import database pool
        from app.core.database_pool import DatabasePool
        
        # Initialize pool if needed
        db_pool = DatabasePool()
        await db_pool.initialize()
        
        if db_pool.session_factory:
            async with db_pool.get_session() as session:
                # Use SQLAlchemy text for raw SQL
                from sqlalchemy import text
                
                query = text("""
                    SELECT 
                        property_id,
                        SUM(total_amount) as total_revenue,
                        COUNT(*) as reservation_count
                    FROM reservations 
                    WHERE property_id = :property_id AND tenant_id = :tenant_id
                    GROUP BY property_id
                """)
                
                result = await session.execute(query, {
                    "property_id": property_id, 
                    "tenant_id": tenant_id
                })
                row = result.fetchone()
                
                if row:
                    total_revenue = Decimal(str(row.total_revenue))
                    return {
                        "property_id": property_id,
                        "tenant_id": tenant_id,
                        "total": _format_money(total_revenue),
                        "currency": "USD", 
                        "count": row.reservation_count
                    }
                else:
                    # No reservations found for this property
                    return {
                        "property_id": property_id,
                        "tenant_id": tenant_id,
                        "total": "0.00",
                        "currency": "USD",
                        "count": 0
                    }
        else:
            raise Exception("Database pool not available")
            
    except Exception as e:
        print(f"Database error for {property_id} (tenant: {tenant_id}): {e}")

        return {
            "property_id": property_id,
            "tenant_id": tenant_id, 
            "total": "0.00",
            "currency": "USD",
            "count": 0
        }
