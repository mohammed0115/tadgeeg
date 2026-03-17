"""
Audit Analytics Service

Extracts comprehensive statistics and insights from audit sessions.

Provides aggregated metrics across multiple dimensions:
- Session-level statistics (duration, completion rates, processing metrics)
- Risk analysis (distribution, trends, severity breakdowns)
- Finding analytics (categories, severities, resolution rates)
- Performance metrics (throughput, efficiency, bottlenecks)
- User/Organization insights

Thread-safe: Uses Django ORM aggregations and F() expressions.
"""

import logging
from datetime import timedelta
from typing import Dict, List, Any, Optional

from django.db import connection
from django.db.models import (
    Q, F, Count, Avg, Sum, Min, Max, Case, When, 
    IntegerField, FloatField, Value, CharField, Exists, OuterRef, Subquery,
    QuerySet
)
from django.utils import timezone

from apps.authentication.models import User, Organization
from apps.audit.models import AuditSession, AuditFinding
from apps.invoices.models import Invoice, InvoiceBatch
from apps.documents.models import Document

logger = logging.getLogger("finai")


class SessionNotFoundError(Exception):
    """Raised when a requested session doesn't exist."""
    pass


class AuditAnalyticsService:
    """Service for extracting and aggregating audit session analytics."""

    def __init__(self, organization: Optional[Organization] = None):
        """
        Initialize analytics service.
        
        Args:
            organization: Filter analytics to specific org (if None, global stats)
        """
        self.organization = organization

    # ────────────────────────────────────────────────────────────────────────────
    # Session-level Statistics
    # ────────────────────────────────────────────────────────────────────────────

    def session_statistics(self, session_id: str) -> Dict[str, Any]:
        """
        Extract detailed statistics for a single audit session.
        
        Returns:
            {
              session_id: uuid,
              state: str,
              documents: {
                total, processed, success, failed, review_required,
                success_rate_pct, average_risk_score
              },
              risk_summary: {
                overall_risk_score, overall_risk_level,
                duplicate_count, high_risk_count, compliance_issues
              },
              timing: {
                created_at, started_at, completed_at,
                processing_time_seconds, total_duration_seconds
              },
              findings: {
                total_findings, by_severity, by_category, open_count
              }
            }
        """
        try:
            session = AuditSession.objects.get(pk=session_id)
        except AuditSession.DoesNotExist:
            raise SessionNotFoundError(f"Session {session_id} not found")

        # Document processing metrics
        total = session.total_count
        processed = session.processed_count
        success_rate = (session.success_count / total * 100) if total > 0 else 0

        # Get average risk from associated invoices
        avg_risk = self._average_invoice_risk(session)

        # Findings summary
        findings_stats = self._findings_summary(session)

        # Timing calculations
        timing = {}
        if session.started_at:
            if session.completed_at:
                processing_time = (session.completed_at - session.started_at).total_seconds()
            else:
                processing_time = (timezone.now() - session.started_at).total_seconds()
            timing["processing_time_seconds"] = processing_time
        else:
            timing["processing_time_seconds"] = None

        if session.created_at and session.completed_at:
            total_duration = (session.completed_at - session.created_at).total_seconds()
            timing["total_duration_seconds"] = total_duration
        else:
            timing["total_duration_seconds"] = None

        return {
            "session_id": str(session.id),
            "state": session.state,
            "session_name": session.session_name or "",
            "documents": {
                "total": session.total_count,
                "processed": session.processed_count,
                "success": session.success_count,
                "failed": session.failed_count,
                "review_required": session.review_required_count,
                "success_rate_pct": round(success_rate, 2),
                "average_risk_score": round(avg_risk, 2),
            },
            "risk_summary": {
                "overall_risk_score": session.overall_risk_score,
                "overall_risk_level": session.overall_risk_level,
                "duplicate_count": session.duplicate_count,
                "high_risk_count": session.high_risk_count,
                "compliance_issues": session.compliance_issues,
            },
            "timing": {
                "created_at": session.created_at.isoformat(),
                "started_at": session.started_at.isoformat() if session.started_at else None,
                "completed_at": session.completed_at.isoformat() if session.completed_at else None,
                **timing,
            },
            "findings": findings_stats,
            "created_by": {
                "user_id": str(session.created_by.id) if session.created_by else None,
                "username": session.created_by.username if session.created_by else None,
            }
        }

    def multi_session_statistics(self, session_ids: List[str]) -> List[Dict[str, Any]]:
        """Batch retrieve statistics for multiple sessions."""
        return [self.session_statistics(sid) for sid in session_ids]

    # ────────────────────────────────────────────────────────────────────────────
    # Organization-level Analytics
    # ────────────────────────────────────────────────────────────────────────────

    def organization_summary(self, days: int = 30) -> Dict[str, Any]:
        """
        Summary analytics for the organization in the last N days.
        
        Args:
            days: Number of days to include (default: 30)
            
        Returns:
            {
              period: str,
              total_sessions, completed_sessions, failed_sessions,
              completion_rate, average_processing_time,
              
              documents: {
                total_uploaded, total_processed, success_count, failed_count,
                average_risk_score, distribution by risk level
              },
              
              findings: {
                total, by_severity, by_category, resolution_status
              },
              
              performance: {
                avg_documents_per_session, throughput_per_day,
                peak_risk_level
              }
            }
        """
        cutoff_date = timezone.now() - timedelta(days=days)
        
        qs = self._base_queryset().filter(created_at__gte=cutoff_date)
        
        # Session-level aggregations
        session_stats = qs.aggregate(
            total_sessions=Count('id'),
            completed_sessions=Count(
                Case(When(state=AuditSession.State.COMPLETED, then=1), output_field=IntegerField())
            ),
            failed_sessions=Count(
                Case(When(state=AuditSession.State.FAILED, then=1), output_field=IntegerField())
            ),
            total_documents=Sum('total_count'),
            successful_documents=Sum('success_count'),
            failed_documents=Sum('failed_count'),
            avg_risk_score=Avg('overall_risk_score'),
        )

        # Document processing metrics
        total_docs = session_stats.get('total_documents') or 0
        total_sessions = session_stats.get('total_sessions') or 0
        processed_docs = session_stats.get('successful_documents') or 0
        
        completion_rate = (
            (session_stats['completed_sessions'] / total_sessions * 100)
            if total_sessions > 0 else 0
        )
        docs_per_session = (total_docs / total_sessions) if total_sessions > 0 else 0

        # Risk distribution
        risk_dist = self._risk_distribution(qs)

        # Findings analysis
        findings_analysis = self._findings_analysis_for_sessions(qs)

        # Processing time
        timing_stats = qs.filter(
            started_at__isnull=False,
            completed_at__isnull=False
        ).extra(
            select={
                'processing_duration': 'EXTRACT(EPOCH FROM (completed_at - started_at))'
            }
        ).aggregate(
            avg_processing_time=Avg('processing_duration')
        )

        return {
            "period": f"Last {days} days",
            "period_start": cutoff_date.isoformat(),
            "period_end": timezone.now().isoformat(),
            
            "sessions": {
                "total": session_stats.get('total_sessions', 0),
                "completed": session_stats.get('completed_sessions', 0),
                "failed": session_stats.get('failed_sessions', 0),
                "completion_rate_pct": round(completion_rate, 2),
            },
            
            "documents": {
                "total_uploaded": total_docs,
                "total_successful": processed_docs,
                "total_failed": session_stats.get('failed_documents', 0),
                "average_per_session": round(docs_per_session, 2),
                "average_risk_score": round(session_stats.get('avg_risk_score', 0), 2),
                "by_risk_level": risk_dist,
            },
            
            "findings": findings_analysis,
            
            "performance": {
                "average_processing_time_seconds": round(
                    timing_stats.get('avg_processing_time') or 0, 2
                ),
                "throughput_documents_per_day": round(
                    (total_docs / max(days, 1)), 2
                ),
            }
        }

    # ────────────────────────────────────────────────────────────────────────────
    # Finding Analytics
    # ────────────────────────────────────────────────────────────────────────────

    def findings_breakdown(
        self, 
        session_id: Optional[str] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Analyze findings: severity, category, resolution status, trends.
        
        Args:
            session_id: If provided, analyze only findings from this session
            days: Days to include in query (default: 30)
            
        Returns:
            {
              by_severity: {critical, high, medium, low},
              by_category: {...},
              by_status: {open, reviewed, resolved, dismissed},
              unresolved_count,
              resolution_rate_pct,
              average_resolution_time_hours,
              trending_categories: list of top categories
            }
        """
        cutoff_date = timezone.now() - timedelta(days=days)
        
        if session_id:
            qs = AuditFinding.objects.filter(
                session_id=session_id,
                created_at__gte=cutoff_date
            )
        else:
            qs = AuditFinding.objects.filter(created_at__gte=cutoff_date)
            if self.organization:
                qs = qs.filter(organization=self.organization)

        # By severity
        severity_breakdown = qs.values('severity').annotate(
            count=Count('id'),
            avg_resolution_time=Avg(
                Case(
                    When(
                        reviewed_at__isnull=False,
                        then=(F('reviewed_at') - F('created_at'))
                    ),
                    output_field=IntegerField()
                )
            )
        ).order_by('severity')

        severity_dict = {
            item['severity']: {
                'count': item['count'],
                'avg_resolution_hours': (
                    round(item['avg_resolution_time'] / 3600, 2)
                    if item['avg_resolution_time'] else None
                )
            }
            for item in severity_breakdown
        }

        # By category
        category_breakdown = qs.values('category').annotate(
            count=Count('id')
        ).order_by('-count')
        
        category_dict = {item['category']: item['count'] for item in category_breakdown}

        # By status
        status_breakdown = qs.values('status').annotate(
            count=Count('id')
        )
        
        status_dict = {
            item['status']: item['count'] for item in status_breakdown
        }

        # Overall metrics
        total_findings = qs.count()
        unresolved = qs.filter(
            Q(status=AuditFinding.Status.OPEN) | Q(status=AuditFinding.Status.REVIEWED)
        ).count()
        
        resolved = qs.filter(status=AuditFinding.Status.RESOLVED).count()
        resolution_rate = (resolved / total_findings * 100) if total_findings > 0 else 0

        return {
            "total_findings": total_findings,
            "by_severity": severity_dict,
            "by_category": category_dict,
            "by_status": status_dict,
            "unresolved_count": unresolved,
            "resolved_count": resolved,
            "resolution_rate_pct": round(resolution_rate, 2),
            "trending_categories": [
                {"category": k, "count": v}
                for k, v in sorted(category_dict.items(), key=lambda x: x[1], reverse=True)[:5]
            ]
        }

    # ────────────────────────────────────────────────────────────────────────────
    # Risk Analytics
    # ────────────────────────────────────────────────────────────────────────────

    def risk_analytics(self, days: int = 30) -> Dict[str, Any]:
        """
        Comprehensive risk analysis across all sessions/documents.
        
        Returns:
            {
              average_risk_score,
              risk_distribution: {critical, high, medium, low},
              high_risk_sessions,
              risk_trend_by_day,
              top_risk_factors: list of most common issues
            }
        """
        cutoff_date = timezone.now() - timedelta(days=days)
        
        qs = self._base_queryset().filter(created_at__gte=cutoff_date)
        
        # Overall risk statistics
        risk_stats = qs.aggregate(
            avg_score=Avg('overall_risk_score'),
            max_score=Max('overall_risk_score'),
            min_score=Min('overall_risk_score'),
        )

        # Risk distribution by level
        risk_dist = self._risk_distribution(qs)

        # High-risk sessions (>= 50)
        high_risk_sessions = qs.filter(overall_risk_score__gte=50).values(
            'id', 'session_name', 'overall_risk_score', 'completed_at'
        ).order_by('-overall_risk_score')[:10]

        # Risk trend by day
        risk_trend = qs.extra(
            select={'date': 'DATE(created_at)'}
        ).values('date').annotate(
            avg_risk=Avg('overall_risk_score'),
            count=Count('id')
        ).order_by('date')

        return {
            "average_risk_score": round(risk_stats['avg_score'] or 0, 2),
            "max_risk_score": risk_stats['max_score'] or 0,
            "min_risk_score": risk_stats['min_score'] or 0,
            "risk_distribution": risk_dist,
            "high_risk_sessions_count": qs.filter(
                overall_risk_score__gte=50
            ).count(),
            "critical_sessions_count": qs.filter(
                overall_risk_score__gte=75
            ).count(),
            "recent_high_risk_sessions": [
                {
                    "session_id": str(s['id']),
                    "session_name": s['session_name'],
                    "risk_score": s['overall_risk_score'],
                    "completed_at": s['completed_at'].isoformat() if s['completed_at'] else None,
                }
                for s in high_risk_sessions
            ],
            "risk_trend": [
                {
                    "date": str(item['date']),
                    "average_risk": round(item['avg_risk'], 2),
                    "sessions": item['count'],
                }
                for item in risk_trend
            ]
        }

    # ────────────────────────────────────────────────────────────────────────────
    # User & Performance Analytics
    # ────────────────────────────────────────────────────────────────────────────

    def user_statistics(self, user_id: str, days: int = 30) -> Dict[str, Any]:
        """Analytics specific to a single user's audit sessions."""
        cutoff_date = timezone.now() - timedelta(days=days)
        
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise ValueError(f"User {user_id} not found")

        qs = AuditSession.objects.filter(
            created_by=user,
            created_at__gte=cutoff_date
        )

        stats = qs.aggregate(
            total_sessions=Count('id'),
            completed=Count(Case(When(state=AuditSession.State.COMPLETED, then=1), output_field=IntegerField())),
            total_documents=Sum('total_count'),
            avg_risk=Avg('overall_risk_score'),
        )

        most_recent = qs.order_by('-created_at').first()

        return {
            "user_id": user_id,
            "username": user.username,
            "period": f"Last {days} days",
            "total_sessions": stats['total_sessions'],
            "completed_sessions": stats['completed'],
            "completion_rate_pct": (
                (stats['completed'] / stats['total_sessions'] * 100)
                if stats['total_sessions'] > 0 else 0
            ),
            "total_documents_processed": stats['total_documents'] or 0,
            "average_risk_score": round(stats['avg_risk'] or 0, 2),
            "most_recent_session": {
                "session_id": str(most_recent.id),
                "state": most_recent.state,
                "created_at": most_recent.created_at.isoformat(),
            } if most_recent else None,
        }

    def performance_report(self, days: int = 30) -> Dict[str, Any]:
        """
        Identify performance bottlenecks and efficiency metrics.
        """
        cutoff_date = timezone.now() - timedelta(days=days)
        
        qs = self._base_queryset().filter(
            created_at__gte=cutoff_date,
            started_at__isnull=False,
            completed_at__isnull=False
        )

        # Calculate processing time per document
        perf_stats = qs.extra(
            select={
                'processing_duration': 'EXTRACT(EPOCH FROM (completed_at - started_at))',
                'docs_per_second': 'CAST(total_count AS FLOAT) / NULLIF(EXTRACT(EPOCH FROM (completed_at - started_at)), 0)'
            }
        ).aggregate(
            avg_duration=Avg('processing_duration'),
            median_duration=Avg('processing_duration'),  # Note: Django doesn't have built-in median
            slowest_duration=Max('processing_duration'),
            fastest_duration=Min('processing_duration'),
        )

        # Sessions with high failure rates
        high_failure_sessions = qs.annotate(
            failure_rate=Case(
                When(total_count__gt=0, then=F('failed_count') * 100.0 / F('total_count')),
                output_field=FloatField()
            )
        ).filter(failure_rate__gt=10).order_by('-failure_rate')[:5]

        return {
            "analysis_period": f"Last {days} days",
            "processing_time": {
                "average_seconds": round(perf_stats['avg_duration'] or 0, 2),
                "slowest_seconds": perf_stats['slowest_duration'] or 0,
                "fastest_seconds": perf_stats['fastest_duration'] or 0,
            },
            "bottleneck_sessions": [
                {
                    "session_id": str(s.id),
                    "total_documents": s.total_count,
                    "processing_time_seconds": (s.completed_at - s.started_at).total_seconds()
                    if s.started_at and s.completed_at else 0,
                    "failure_rate_pct": getattr(s, 'failure_rate', 0),
                }
                for s in high_failure_sessions
            ]
        }

    # ────────────────────────────────────────────────────────────────────────────
    # Helper Methods
    # ────────────────────────────────────────────────────────────────────────────

    def _base_queryset(self) -> QuerySet:
        """Get base queryset filtered by organization (if set)."""
        qs = AuditSession.objects.all()
        if self.organization:
            qs = qs.filter(organization=self.organization)
        return qs

    def _average_invoice_risk(self, session: AuditSession) -> float:
        """Get average risk score from invoices in session's batches."""
        try:
            avg = Invoice.objects.filter(
                batch__audit_session=session
            ).aggregate(avg_risk=Avg('risk_score'))
            return avg.get('avg_risk') or 0.0
        except Exception:
            return 0.0

    def _risk_distribution(self, queryset: QuerySet) -> Dict[str, int]:
        """Get count of sessions by risk level."""
        distribution = queryset.aggregate(
            critical=Count(Case(
                When(overall_risk_score__gte=75, then=1),
                output_field=IntegerField()
            )),
            high=Count(Case(
                When(overall_risk_score__gte=50, overall_risk_score__lt=75, then=1),
                output_field=IntegerField()
            )),
            medium=Count(Case(
                When(overall_risk_score__gte=25, overall_risk_score__lt=50, then=1),
                output_field=IntegerField()
            )),
            low=Count(Case(
                When(overall_risk_score__lt=25, then=1),
                output_field=IntegerField()
            )),
        )
        return distribution

    def _findings_summary(self, session: AuditSession) -> Dict[str, Any]:
        """Get findings summary for a session."""
        findings_qs = AuditFinding.objects.filter(session=session)
        
        severity_counts = findings_qs.values('severity').annotate(
            count=Count('id')
        )
        
        category_counts = findings_qs.values('category').annotate(
            count=Count('id')
        )
        
        status_counts = findings_qs.values('status').annotate(
            count=Count('id')
        )

        return {
            "total_findings": findings_qs.count(),
            "by_severity": {item['severity']: item['count'] for item in severity_counts},
            "by_category": {item['category']: item['count'] for item in category_counts},
            "by_status": {item['status']: item['count'] for item in status_counts},
            "open_count": findings_qs.filter(
                status=AuditFinding.Status.OPEN
            ).count(),
        }

    def _findings_analysis_for_sessions(self, session_qs: QuerySet) -> Dict[str, Any]:
        """Analyze findings for a queryset of sessions."""
        findings_qs = AuditFinding.objects.filter(session__in=session_qs)
        
        total = findings_qs.count()
        
        severity_breakdown = findings_qs.values('severity').annotate(
            count=Count('id')
        )
        
        category_breakdown = findings_qs.values('category').annotate(
            count=Count('id')
        ).order_by('-count')
        
        status_breakdown = findings_qs.values('status').annotate(
            count=Count('id')
        )

        return {
            "total": total,
            "by_severity": {item['severity']: item['count'] for item in severity_breakdown},
            "by_category": {item['category']: item['count'] for item in category_breakdown},
            "by_status": {item['status']: item['count'] for item in status_breakdown},
            "unresolved": findings_qs.filter(
                status__in=[AuditFinding.Status.OPEN, AuditFinding.Status.REVIEWED]
            ).count(),
        }
