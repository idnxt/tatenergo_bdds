"""
ORM-модели. Отражают схему БД один-в-один.
Для создания таблиц используется миграция 001_init.sql,
модели нужны для удобных запросов в отчётах.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.engine import Base


class Region(Base):
    """Справочник регионов. Пока code == name, заполняется при импорте."""
    __tablename__ = "regions"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    charges: Mapped[list["Charge"]] = relationship(back_populates="region_ref")


class ImportLog(Base):
    """Один файл = одна запись. Повторная загрузка того же месяца запрещена."""
    __tablename__ = "import_log"
    __table_args__ = (UniqueConstraint("period_from", name="uq_import_period"),)

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_from: Mapped[date]     = mapped_column(Date, nullable=False)
    period_to:   Mapped[date]     = mapped_column(Date, nullable=False)
    filename:    Mapped[Optional[str]] = mapped_column(String(255))
    filesum:     Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))  # из #FILESUM
    loaded_at:   Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    row_count:   Mapped[Optional[int]] = mapped_column(Integer)
    error_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer)  # время импорта

    charges: Mapped[list["Charge"]] = relationship(back_populates="import_ref")


class Charge(Base):
    """Основная таблица: одна строка файла = одна запись."""
    __tablename__ = "charges"

    id:           Mapped[int]  = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    import_id:    Mapped[int]  = mapped_column(Integer, ForeignKey("import_log.id"), nullable=False)
    region:       Mapped[str]  = mapped_column(String(30), ForeignKey("regions.code"), nullable=False)
    account_id:   Mapped[str]  = mapped_column(String(30), nullable=False)
    total_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    period_from:  Mapped[date] = mapped_column(Date, nullable=False)
    period_to:    Mapped[date] = mapped_column(Date, nullable=False)

    import_ref:   Mapped["ImportLog"]          = relationship(back_populates="charges")
    region_ref:   Mapped["Region"]             = relationship(back_populates="charges")
    providers:    Mapped[list["ChargeProvider"]] = relationship(back_populates="charge")
    meters:       Mapped[list["MeterReading"]]   = relationship(back_populates="charge")
    tariffs:      Mapped[list["TariffCalc"]]     = relationship(back_populates="charge")


class Provider(Base):
    """Справочник поставщиков. Накапливается по мере загрузки файлов."""
    __tablename__ = "providers"

    id:   Mapped[int] = mapped_column(Integer, primary_key=True)  # id из файла
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    charge_providers: Mapped[list["ChargeProvider"]] = relationship(back_populates="provider")


class ChargeProvider(Base):
    """Начисление по конкретному поставщику для конкретного лицевого счёта."""
    __tablename__ = "charge_providers"

    id:          Mapped[int]     = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    charge_id:   Mapped[int]     = mapped_column(BigInteger, ForeignKey("charges.id"), nullable=False)
    provider_id: Mapped[int]     = mapped_column(Integer, ForeignKey("providers.id"), nullable=False)
    amount:      Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))

    charge:   Mapped["Charge"]   = relationship(back_populates="providers")
    provider: Mapped["Provider"] = relationship(back_populates="charge_providers")


class MeterReading(Base):
    """
    Показание прибора учёта за расчётный месяц.
    Несколько приборов одного типа (например 2x ХВС) различаются meter_number.
    meter_number может содержать "/" для приборов с несколькими тарифами.
    """
    __tablename__ = "meter_readings"

    id:             Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    charge_id:      Mapped[int] = mapped_column(BigInteger, ForeignKey("charges.id"), nullable=False)
    meter_type_id:  Mapped[int] = mapped_column(Integer, nullable=False)   # порядковый номер из Pu
    meter_type_name: Mapped[str] = mapped_column(String(100), nullable=False)
    meter_number:   Mapped[str] = mapped_column(String(50), nullable=False)
    reading:        Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 3))

    charge: Mapped["Charge"] = relationship(back_populates="meters")


class TariffCalc(Base):
    """
    Расчётный тариф и аномалии.
    Заполняется после импорта на основе MeterReading текущего и предыдущего месяца.
    anomaly_reason — текстовое поле: логика аномалий добавляется без миграций.
    """
    __tablename__ = "tariff_calc"

    id:             Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    charge_id:      Mapped[int] = mapped_column(BigInteger, ForeignKey("charges.id"), nullable=False)
    meter_type_id:  Mapped[int] = mapped_column(Integer, nullable=False)
    meter_number:   Mapped[str] = mapped_column(String(50), nullable=False)
    reading_curr:   Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 3))
    reading_prev:   Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 3))
    consumption:    Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 3))  # curr - prev
    amount:         Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))  # от ТАТЭНЕРГОСБЫТ
    tariff_calc:    Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 5))  # amount / consumption
    is_anomaly:     Mapped[bool]              = mapped_column(Boolean, default=False)
    anomaly_reason: Mapped[Optional[str]]     = mapped_column(Text)

    charge: Mapped["Charge"] = relationship(back_populates="tariffs")
