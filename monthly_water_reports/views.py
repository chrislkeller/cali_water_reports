from __future__ import division
from django.conf import settings
from django.shortcuts import get_object_or_404, render_to_response, render
from django.template.loader import render_to_string
from django.http import HttpResponseRedirect, HttpResponse, HttpResponseBadRequest, Http404
from django.views.decorators.clickjacking import xframe_options_exempt, xframe_options_sameorigin
from django.core.urlresolvers import reverse
from django.template import RequestContext, Context, loader
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views.generic import View, ListView, DetailView
from django.db.models import Q, Avg, Max, Min, Sum, Count
from monthly_water_reports.models import WaterSupplier, WaterSupplierMonthlyReport, WaterEnforcementMonthlyReport, WaterIncentive, WaterRestriction, WaterConservationMethod, HydrologicRegion
from bakery.views import BuildableListView, BuildableDetailView
import os
import calculate
import datetime
import logging
import yaml
import calendar
import math

logger = logging.getLogger("cali_water_reports")

# Create your views here.
class InitialIndex(BuildableListView):

    model = WaterSupplierMonthlyReport

    template_name = "monthly_water_reports/index.html"

    def get_object(self):
        object = super(InitialIndex, self).get_object()
        return object

    def get_queryset(self):

        # grab the yaml configuration items
        config = yaml.load(open("monthly_water_reports/display_config.yml"))

        # get all the reports
        queryset = super(InitialIndex, self).get_queryset()

        # get all of the water suppliers
        water_suppliers = WaterSupplier.objects.exclude(supplier_active=False)

        # new instance of the utility class
        new_queries = QueryUtilities()

        # queryset of the latest month of data from the most recent report
        latest_month_latest_report = new_queries._latest_month_latest_report(queryset)

        # queryset of all the months of data from the most recent report
        all_months_latest_report = new_queries._all_months_latest_report(queryset)

        # list of months available in the most recent report
        months_in_report = all_months_latest_report.exclude(reporting_month__isnull=True).values("reporting_month").distinct().order_by("-reporting_month")

        # get the max value of calculated_rgpcd_2014 in the latest report
        global_max = latest_month_latest_report.values("calculated_rgpcd_2014").aggregate(Max("calculated_rgpcd_2014"))

        # get the min value of calculated_rgpcd_2014 in the latest report
        global_min = latest_month_latest_report.values("calculated_rgpcd_2014").aggregate(Min("calculated_rgpcd_2014"))

        # create the hydrologic_region option list
        hydrologic_regions = water_suppliers.exclude(hydrologic_region__isnull=True).values("hydrologic_region").distinct()

        for item in hydrologic_regions:
            item["suppliers"] = water_suppliers.filter(hydrologic_region = item["hydrologic_region"]).order_by("supplier_name")

        # create the hydrologic_region data for the maps
        map_data = water_suppliers.exclude(hydrologic_region__isnull=True).values("hydrologic_region").distinct().order_by("hydrologic_region")

        for item in map_data:
            this_month = all_months_latest_report.filter(hydrologic_region = item["hydrologic_region"]).filter(reporting_month = months_in_report[0]["reporting_month"])
            item["this_month_avg"] = new_queries._get_avg_rgcpd(this_month)

            item["this_month_baseline_avg"] = new_queries._get_last_year_avg_rgcpd(this_month)

            last_month = all_months_latest_report.filter(hydrologic_region = item["hydrologic_region"]).filter(reporting_month = months_in_report[1]["reporting_month"])
            item["last_month_avg"] = new_queries._get_avg_rgcpd(last_month)

            item["suppliers"] = list(latest_month_latest_report.filter(hydrologic_region = item["hydrologic_region"]).values("supplier_name", "calculated_rgpcd_2014").order_by("calculated_rgpcd_2014"))

            item["count"] = latest_month_latest_report.filter(hydrologic_region = item["hydrologic_region"]).count()

            item["this_max"] = latest_month_latest_report.filter(hydrologic_region = item["hydrologic_region"]).values("calculated_rgpcd_2014").aggregate(Max("calculated_rgpcd_2014"))

            item["this_min"] = latest_month_latest_report.filter(hydrologic_region = item["hydrologic_region"]).values("calculated_rgpcd_2014").aggregate(Min("calculated_rgpcd_2014"))

            item["median"] =  latest_month_latest_report.filter(hydrologic_region = item["hydrologic_region"]).values_list("calculated_rgpcd_2014", flat=True).order_by("calculated_rgpcd_2014")[int(round(item["count"]/2))]

            item["min_range"] = new_queries.pct_value_inside_arbitrary_range(item["this_min"]["calculated_rgpcd_2014__min"], global_min["calculated_rgpcd_2014__min"], global_max["calculated_rgpcd_2014__max"])

            item["max_range"] = new_queries.pct_value_inside_arbitrary_range(item["this_max"]["calculated_rgpcd_2014__max"], global_min["calculated_rgpcd_2014__min"], global_max["calculated_rgpcd_2014__max"])

            item["median_range"] = new_queries.pct_value_inside_arbitrary_range(item["median"], global_min["calculated_rgpcd_2014__min"], global_max["calculated_rgpcd_2014__max"])

            item["average_range"] = new_queries.pct_value_inside_arbitrary_range(item["this_month_avg"], global_min["calculated_rgpcd_2014__min"], global_max["calculated_rgpcd_2014__max"])

            for supplier in item["suppliers"]:
                supplier["distribution_percent"] = new_queries.pct_value_inside_arbitrary_range(supplier["calculated_rgpcd_2014"], global_min["calculated_rgpcd_2014__min"], global_max["calculated_rgpcd_2014__max"])

        # calculate the state average rgcpd for the current month
        state_this_month = all_months_latest_report.filter(reporting_month = months_in_report[0]["reporting_month"])
        state_avg_latest = new_queries._get_avg_rgcpd(state_this_month)

        # calculate the state average rgcpd for last month
        state_last_month = all_months_latest_report.filter(reporting_month = months_in_report[1]["reporting_month"])
        state_avg_last = new_queries._get_avg_rgcpd(state_last_month)

        return {
            "article_content": config["article_content"],
            "about_content": config["about_content"],
            "config_object": config["config_object"],
            "target_report": latest_month_latest_report[0].reporting_month,
            "option_list": hydrologic_regions,
            "map_data": list(map_data),
            "global_max": global_max,
            "global_min": global_min,
            "state_avg_latest": state_avg_latest,
            "state_avg_last": state_avg_last,
        }


class RegionDetailView(BuildableDetailView):

    model = HydrologicRegion

    template_name = "monthly_water_reports/region_detail.html"

    slug_field = "hydrologic_region_slug"

    sub_directory = "region/"

    def get_object(self):
        object = super(RegionDetailView, self).get_object()
        return object

    def get_url(self, obj):
        """
        the url at which the detail page should appear.
        """
        return "/%s/" % (obj.hydrologic_region_slug)

    def get_build_path(self, obj):
        """
        used to determine where to build the detail page. override this if you
        would like your detail page at a different location. by default it
        will be built at get_url() + "index.html"
        """
        path = os.path.join(settings.BUILD_DIR, self.sub_directory, self.get_url(obj)[1:])
        os.path.exists(path) or os.makedirs(path)
        return os.path.join(path, "index.html")

    def get_context_data(self, **kwargs):

        # grab the yaml configuration items
        config = yaml.load(open("monthly_water_reports/display_config.yml"))

        # create the context object
        context = super(RegionDetailView, self).get_context_data(**kwargs)

        # add the article content config to the context
        context["article_content"] = config["article_content"]

        # add the about this to the context
        context["about_content"] = config["about_content"]

        # add the javascript config to the context
        context["config_object"] = config["config_object"]

        # get the supplier slug
        context["region_slug"] = self.object.hydrologic_region_slug

        # get the supplier slug
        context["region_name"] = self.object.hydrologic_region

        # get a queryset for this hydrologic region
        queryset = WaterSupplierMonthlyReport.objects.filter(hydrologic_region=context["region_name"]).order_by("supplier_name_id")

        # new instance of the utility class
        new_queries = QueryUtilities()

        # queryset of the latest month of data from the most recent report
        latest_month_latest_report = new_queries._latest_month_latest_report(queryset)

        # queryset of all the months of data from the most recent report
        all_months_latest_report = new_queries._all_months_latest_report(queryset)

        # list of months available in the most recent report
        months_in_report = all_months_latest_report.exclude(reporting_month__isnull=True).values("reporting_month").distinct().order_by("-reporting_month")

        # get the max value of calculated_rgpcd_2014 in the latest report
        context["global_max"] = latest_month_latest_report.values("calculated_rgpcd_2014").aggregate(Max("calculated_rgpcd_2014"))

        # get the min value of calculated_rgpcd_2014 in the latest report
        context["global_min"] = latest_month_latest_report.values("calculated_rgpcd_2014").aggregate(Min("calculated_rgpcd_2014"))

        context["target_report"] = latest_month_latest_report[0].reporting_month

        context["reports_from_region"] = latest_month_latest_report

        # create the hydrologic_region data for the maps
        context["map_data"] = []

        item = {}

        item["hydrologic_slug"] = context["region_slug"]

        item["hydrologic_region"] = context["region_name"]

        # create the hydrologic_region data for the overview
        this_month = all_months_latest_report.filter(hydrologic_region = context["region_name"]).filter(reporting_month = months_in_report[0]["reporting_month"])
        item["this_month_avg"] = new_queries._get_avg_rgcpd(this_month)

        this_month_baseline_avg = new_queries._get_last_year_avg_rgcpd(this_month)
        item["this_month_baseline_avg"] = this_month_baseline_avg

        last_month = all_months_latest_report.filter(hydrologic_region = context["region_name"]).filter(reporting_month = months_in_report[1]["reporting_month"])
        item["last_month_avg"] = new_queries._get_avg_rgcpd(last_month)

        item["suppliers"] = list(latest_month_latest_report.filter(hydrologic_region = context["region_name"]).values("supplier_name", "supplier_slug", "reporting_month", "calculated_rgpcd_2013", "calculated_rgpcd_2014", "calculated_production_monthly_gallons_month_2014", "calculated_production_monthly_gallons_month_2013", "percent_residential_use").order_by("supplier_name_id", "calculated_rgpcd_2013", "calculated_rgpcd_2014"))

        item["count"] = latest_month_latest_report.filter(hydrologic_region = context["region_name"]).count()

        item["this_max"] = latest_month_latest_report.filter(hydrologic_region = context["region_name"]).values("calculated_rgpcd_2014").aggregate(Max("calculated_rgpcd_2014"))

        item["this_min"] = latest_month_latest_report.filter(hydrologic_region = context["region_name"]).values("calculated_rgpcd_2014").aggregate(Min("calculated_rgpcd_2014"))

        item["median"] =  latest_month_latest_report.filter(hydrologic_region = context["region_name"]).values_list("calculated_rgpcd_2014", flat=True).order_by("calculated_rgpcd_2014")[int(round(item["count"]/2))]

        item["min_range"] = new_queries.pct_value_inside_arbitrary_range(item["this_min"]["calculated_rgpcd_2014__min"], context["global_min"]["calculated_rgpcd_2014__min"], context["global_max"]["calculated_rgpcd_2014__max"])

        item["max_range"] = new_queries.pct_value_inside_arbitrary_range(item["this_max"]["calculated_rgpcd_2014__max"], context["global_min"]["calculated_rgpcd_2014__min"], context["global_max"]["calculated_rgpcd_2014__max"])

        item["median_range"] = new_queries.pct_value_inside_arbitrary_range(item["median"], context["global_min"]["calculated_rgpcd_2014__min"], context["global_max"]["calculated_rgpcd_2014__max"])

        item["average_range"] = new_queries.pct_value_inside_arbitrary_range(item["this_month_avg"], context["global_min"]["calculated_rgpcd_2014__min"], context["global_max"]["calculated_rgpcd_2014__max"])

        item["achieved_target"] = []
        item["missed_target"] = []
        item["failed_target"] = []
        item["no_data"] = []

        for supplier in item["suppliers"]:

            supplier["distribution_percent"] = new_queries.pct_value_inside_arbitrary_range(supplier["calculated_rgpcd_2014"], context["global_min"]["calculated_rgpcd_2014__min"], context["global_max"]["calculated_rgpcd_2014__max"])

            supplier_info = WaterSupplier.objects.get(supplier_slug = supplier["supplier_slug"])

            baseline_usage_list = [
                supplier_info.production_2013_june,
                supplier_info.production_2013_july,
                supplier_info.production_2013_aug,
                supplier_info.production_2013_sept,
                supplier_info.production_2013_oct,
                supplier_info.production_2013_nov,
                supplier_info.production_2013_dec,
                supplier_info.production_2013_jan,
                supplier_info.production_2013_feb,
            ]

            current_usage_list = all_months_latest_report.filter(supplier_slug = supplier["supplier_slug"]).filter(reporting_month__gte = "2015-06-01").filter(reporting_month__lte = "2016-02-29").values_list("calculated_production_monthly_gallons_month_2014", flat=True).order_by("calculated_production_monthly_gallons_month_2014")

            # supplier["cum_data"] = new_queries._create_cumulative_savings(current_usage_list, baseline_usage_list, supplier_info.june_11_reduction, supplier["supplier_slug"])

            # if supplier["cum_data"] == None:
            #     item["no_data"].append(supplier["supplier_slug"])
            # else:
            #     if supplier["cum_data"]["cum_success"] == True:
            #         item["achieved_target"].append(supplier["supplier_slug"])
            #     else:
            #         if supplier["cum_data"]["cum_output"] == "narrowly missed":
            #             item["missed_target"].append(supplier["supplier_slug"])
            #         elif supplier["cum_data"]["cum_output"] == "failed to meet":
            #             item["failed_target"].append(supplier["supplier_slug"])

        context["map_data"].append(item)

        return context


class RegionEmbedView(BuildableDetailView):

    model = HydrologicRegion

    template_name = "monthly_water_reports/region_embed.html"

    slug_field = "hydrologic_region_slug"

    sub_directory = "share/"

    def get_object(self):
        object = super(RegionEmbedView, self).get_object()
        return object

    def get_url(self, obj):
        """
        the url at which the detail page should appear.
        """
        return "/%s/" % (obj.hydrologic_region_slug)

    def get_build_path(self, obj):
        """
        used to determine where to build the detail page. override this if you
        would like your detail page at a different location. by default it
        will be built at get_url() + "index.html"
        """
        path = os.path.join(settings.BUILD_DIR, self.sub_directory, self.get_url(obj)[1:])
        os.path.exists(path) or os.makedirs(path)
        return os.path.join(path, "index.html")

    def get_context_data(self, **kwargs):

        # grab the yaml configuration items
        config = yaml.load(open("monthly_water_reports/display_config.yml"))

        # create the context object
        context = super(RegionEmbedView, self).get_context_data(**kwargs)

        # add the article content config to the context
        context["article_content"] = config["article_content"]

        # add the about this to the context
        context["about_content"] = config["about_content"]

        # add the javascript config to the context
        context["config_object"] = config["config_object"]

        # get the supplier slug
        context["region_slug"] = self.object.hydrologic_region_slug

        # get the supplier slug
        context["region_name"] = self.object.hydrologic_region

        # get a queryset for this hydrologic region
        queryset = WaterSupplierMonthlyReport.objects.filter(hydrologic_region=context["region_name"]).order_by("supplier_name_id")

        # new instance of the utility class
        new_queries = QueryUtilities()

        # queryset of the latest month of data from the most recent report
        latest_month_latest_report = new_queries._latest_month_latest_report(queryset)

        # queryset of all the months of data from the most recent report
        all_months_latest_report = new_queries._all_months_latest_report(queryset)

        # list of months available in the most recent report
        months_in_report = all_months_latest_report.exclude(reporting_month__isnull=True).values("reporting_month").distinct().order_by("-reporting_month")

        # get the max value of calculated_rgpcd_2014 in the latest report
        context["global_max"] = latest_month_latest_report.values("calculated_rgpcd_2014").aggregate(Max("calculated_rgpcd_2014"))

        # get the min value of calculated_rgpcd_2014 in the latest report
        context["global_min"] = latest_month_latest_report.values("calculated_rgpcd_2014").aggregate(Min("calculated_rgpcd_2014"))

        context["target_report"] = latest_month_latest_report[0].reporting_month

        context["reports_from_region"] = latest_month_latest_report

        # create the hydrologic_region data for the maps
        context["map_data"] = []

        item = {}

        item["hydrologic_slug"] = context["region_slug"]

        item["hydrologic_region"] = context["region_name"]

        # create the hydrologic_region data for the overview
        this_month = all_months_latest_report.filter(hydrologic_region = context["region_name"]).filter(reporting_month = months_in_report[0]["reporting_month"])
        item["this_month_avg"] = new_queries._get_avg_rgcpd(this_month)

        this_month_baseline_avg = new_queries._get_last_year_avg_rgcpd(this_month)
        item["this_month_baseline_avg"] = this_month_baseline_avg

        last_month = all_months_latest_report.filter(hydrologic_region = context["region_name"]).filter(reporting_month = months_in_report[1]["reporting_month"])
        item["last_month_avg"] = new_queries._get_avg_rgcpd(last_month)

        item["suppliers"] = list(latest_month_latest_report.filter(hydrologic_region = context["region_name"]).values("supplier_name", "supplier_slug", "reporting_month", "calculated_rgpcd_2013", "calculated_rgpcd_2014", "calculated_production_monthly_gallons_month_2014", "calculated_production_monthly_gallons_month_2013", "percent_residential_use").order_by("supplier_name_id", "calculated_rgpcd_2013", "calculated_rgpcd_2014"))

        item["count"] = latest_month_latest_report.filter(hydrologic_region = context["region_name"]).count()

        item["this_max"] = latest_month_latest_report.filter(hydrologic_region = context["region_name"]).values("calculated_rgpcd_2014").aggregate(Max("calculated_rgpcd_2014"))

        item["this_min"] = latest_month_latest_report.filter(hydrologic_region = context["region_name"]).values("calculated_rgpcd_2014").aggregate(Min("calculated_rgpcd_2014"))

        item["median"] =  latest_month_latest_report.filter(hydrologic_region = context["region_name"]).values_list("calculated_rgpcd_2014", flat=True).order_by("calculated_rgpcd_2014")[int(round(item["count"]/2))]

        item["min_range"] = new_queries.pct_value_inside_arbitrary_range(item["this_min"]["calculated_rgpcd_2014__min"], context["global_min"]["calculated_rgpcd_2014__min"], context["global_max"]["calculated_rgpcd_2014__max"])

        item["max_range"] = new_queries.pct_value_inside_arbitrary_range(item["this_max"]["calculated_rgpcd_2014__max"], context["global_min"]["calculated_rgpcd_2014__min"], context["global_max"]["calculated_rgpcd_2014__max"])

        item["median_range"] = new_queries.pct_value_inside_arbitrary_range(item["median"], context["global_min"]["calculated_rgpcd_2014__min"], context["global_max"]["calculated_rgpcd_2014__max"])

        item["average_range"] = new_queries.pct_value_inside_arbitrary_range(item["this_month_avg"], context["global_min"]["calculated_rgpcd_2014__min"], context["global_max"]["calculated_rgpcd_2014__max"])

        for supplier in item["suppliers"]:

            supplier["distribution_percent"] = new_queries.pct_value_inside_arbitrary_range(supplier["calculated_rgpcd_2014"], context["global_min"]["calculated_rgpcd_2014__min"], context["global_max"]["calculated_rgpcd_2014__max"])

        context["map_data"].append(item)

        return context


class ComparisonIndex(BuildableDetailView):

    model = HydrologicRegion

    template_name = "monthly_water_reports/region_reduction_comparison.html"

    slug_field = "hydrologic_region_slug"

    sub_directory = "region/"

    def get_object(self):
        object = super(ComparisonIndex, self).get_object()
        return object

    def get_url(self, obj):
        """
        the url at which the detail page should appear.
        """
        return "/%s/" % (obj.hydrologic_region_slug)

    def get_build_path(self, obj):
        """
        used to determine where to build the detail page. override this if you
        would like your detail page at a different location. by default it
        will be built at get_url() + "index.html"
        """
        path = os.path.join(settings.BUILD_DIR, self.sub_directory, self.get_url(obj)[1:])
        path = "%sreduction-comparison/" % (path)
        os.path.exists(path) or os.makedirs(path)
        return os.path.join(path, "index.html")

    def get_context_data(self, **kwargs):

        # grab the yaml configuration items
        config = yaml.load(open("monthly_water_reports/display_config.yml"))

        # create the context object
        context = super(ComparisonIndex, self).get_context_data(**kwargs)

        # add the article content config to the context
        context["article_content"] = config["article_content"]

        # add the about this to the context
        context["about_content"] = config["about_content"]

        # add the javascript config to the context
        context["config_object"] = config["config_object"]

        # get the supplier slug
        context["region_slug"] = self.object.hydrologic_region_slug

        # get the supplier slug
        context["region_name"] = self.object.hydrologic_region

        # get all of the water suppliers
        context["water_suppliers"] = WaterSupplier.objects.all().filter(hydrologic_region = context["region_name"]).order_by("hydrologic_region", "supplier_name")

        return context


class EnforcementIndex(BuildableDetailView):

    model = HydrologicRegion

    template_name = "monthly_water_reports/region_enforcement_comparison.html"

    slug_field = "hydrologic_region_slug"

    sub_directory = "region/"

    def get_object(self):
        object = super(EnforcementIndex, self).get_object()
        return object

    def get_url(self, obj):
        """
        the url at which the detail page should appear.
        """
        return "/%s/" % (obj.hydrologic_region_slug)

    def get_build_path(self, obj):
        """
        used to determine where to build the detail page. override this if you
        would like your detail page at a different location. by default it
        will be built at get_url() + "index.html"
        """
        path = os.path.join(settings.BUILD_DIR, self.sub_directory, self.get_url(obj)[1:])
        path = "%senforcement-comparison/" % (path)
        os.path.exists(path) or os.makedirs(path)
        return os.path.join(path, "index.html")

    def get_context_data(self, **kwargs):

        # grab the yaml configuration items
        config = yaml.load(open("monthly_water_reports/display_config.yml"))

        # create the context object
        context = super(EnforcementIndex, self).get_context_data(**kwargs)

        # add the article content config to the context
        context["article_content"] = config["article_content"]

        # add the about this to the context
        context["about_content"] = config["about_content"]

        # add the javascript config to the context
        context["config_object"] = config["config_object"]

        # get the supplier slug
        context["region_slug"] = self.object.hydrologic_region_slug

        # get the supplier slug
        context["region_name"] = self.object.hydrologic_region

        # get all the reports
        queryset = WaterEnforcementMonthlyReport.objects.filter(hydrologic_region = context["region_name"]).order_by("hydrologic_region", "supplier_name")

        context["water_suppliers"] = queryset.values("supplier_name", "hydrologic_region") \
            .annotate(sum_complaints_received = Sum("complaints_received")) \
            .annotate(sum_follow_up_actions = Sum("follow_up_actions")) \
            .annotate(sum_warnings_issued = Sum("warnings_issued")) \
            .annotate(sum_penalties_assessed = Sum("penalties_assessed")) \
            .annotate(reporting_month_min = Min("reporting_month")) \
            .annotate(reporting_month_max = Max("reporting_month"))

        return context


class SupplierDetailView(BuildableDetailView):

    model = WaterSupplier

    template_name = "monthly_water_reports/supplier_detail.html"

    slug_field = "supplier_slug"

    def get_object(self):
        object = super(SupplierDetailView, self).get_object()
        return object

    def get_url(self, obj):
        """
        the url at which the detail page should appear.
        """
        return "/%s" % (obj.supplier_slug)

    def get_build_path(self, obj):
        """
        used to determine where to build the detail page. override this if you
        would like your detail page at a different location. by default it
        will be built at get_url() + "index.html"
        """
        path = os.path.join(settings.BUILD_DIR, self.get_url(obj)[1:])
        os.path.exists(path) or os.makedirs(path)
        return os.path.join(path, "index.html")

    def get_context_data(self, **kwargs):

        # grab the yaml configuration items
        config = yaml.load(open("monthly_water_reports/display_config.yml"))

        # create the context object
        context = super(SupplierDetailView, self).get_context_data(**kwargs)

        # add the article content config to the context
        context["article_content"] = config["article_content"]

        # add the about this to the context
        context["about_content"] = config["about_content"]

        # add the javascript config to the context
        context["config_object"] = config["config_object"]

        # get the supplier slug
        context["slug"] = self.object.supplier_slug

        # get all the reports
        queryset = WaterSupplierMonthlyReport.objects.all()

        # create instance of query class
        new_queries = QueryUtilities()

        # get queryset of the latest month from the most recent report
        latest_month_latest_report = new_queries._latest_month_latest_report(queryset)

        # calculate & return the state average rgcpd for the current month
        context["latest_state_avg"] = new_queries._get_avg_rgcpd(latest_month_latest_report)

        # get & return queryset of all the months from the most recent report
        all_months_latest_report = new_queries._all_months_latest_report(queryset)

        context["results"] = all_months_latest_report.filter(supplier_name_id = self.object)

        context["april_7_tier"] = {
            "conservation_standard": self.object.april_7_reduction,
            "conservation_placement": self.object.april_7_rgpcd,
            "conservation_tier": self.object.april_7_tier,
        }

        context["april_18_tier"] = {
            "conservation_standard": self.object.april_18_reduction,
            "conservation_placement": self.object.april_18_rgpcd,
            "conservation_tier": self.object.april_18_tier,
        }

        context["april_28_tier"] = {
            "conservation_standard": self.object.april_28_reduction,
            "conservation_placement": self.object.april_28_rgpcd,
            "conservation_tier": self.object.april_28_tier,
        }

        context["final_tier"] = {
            "conservation_standard": self.object.june_11_reduction,
            "conservation_placement": self.object.june_11_rgpcd,
            "conservation_tier": self.object.june_11_tier,
            "conservation_savings": self.object.june_11_estimated_savings,
        }

        # return the restrictions if present
        context["restrictions"] = WaterRestriction.objects.filter(supplier_name_id = self.object)

        # return the incentives if present
        context["incentives"] = WaterIncentive.objects.filter(supplier_name_id = self.object)

        # return the conservation_methods if present
        context["conservation_methods"] = WaterConservationMethod.objects.all().order_by("?")[:4]

        context["target_report"] = latest_month_latest_report[0].reporting_month

        # calculate cumulative savings for an agency
        current_usage_list = context["results"].filter(reporting_month__gte = "2015-06-01").values_list("calculated_production_monthly_gallons_month_2014", flat=True).order_by("calculated_production_monthly_gallons_month_2014")

        baseline_usage_list = [
            self.object.production_2013_june,
            self.object.production_2013_july,
            self.object.production_2013_aug,
            self.object.production_2013_sept,
            self.object.production_2013_oct,
            self.object.production_2013_nov,
            self.object.production_2013_dec,
            self.object.production_2013_jan,
            self.object.production_2013_feb,
        ]

        # context["cumulative_calcs"] = new_queries._create_cumulative_savings(current_usage_list, baseline_usage_list, self.object.june_11_reduction, self.object.supplier_slug)

        # create the lists needed for the rgpcd charts
        context["labels"] = []
        context["data_2014"] = []
        context["data_2013"] = []

        for result in context["results"]:
            month_label = result.reporting_month.strftime("%b %Y")
            context["labels"].append(month_label)
            context["data_2014"].append(result.calculated_rgpcd_2014)
            context["data_2013"].append(result.calculated_rgpcd_2013)

        context["enforcement_stats"] = WaterEnforcementMonthlyReport.objects.filter(supplier_name = self.object).order_by("-reporting_month")

        # return the context
        return context

class QueryUtilities(object):

    def _latest_month_latest_report(self, queryset):
        """
        get the most recent month's data from the most recent report submitted to the state
        """
        latest_data = queryset.aggregate(Max("reporting_month"))
        latest_report_date = queryset.aggregate(Max("report_date"))
        target_report = datetime.date(latest_data["reporting_month__max"].year, latest_data["reporting_month__max"].month, latest_data["reporting_month__max"].day)
        output = queryset.filter(report_date = latest_report_date["report_date__max"]).filter(reporting_month__gte = target_report)
        return output


    def _all_months_latest_report(self, queryset):
        """
        get the all the months of data from the most recent report submitted to the state
        """
        latest_data = queryset.aggregate(Max("reporting_month"))
        latest_report_date = queryset.aggregate(Max("report_date"))
        target_report = datetime.date(latest_data["reporting_month__max"].year, latest_data["reporting_month__max"].month, latest_data["reporting_month__max"].day)
        output = queryset.filter(report_date = latest_report_date["report_date__max"]).order_by("-reporting_month")
        return output


    def _get_avg_rgcpd(self, queryset):
        """
        get the average residential gallons per capita per day for this last year for suppliers in a queryset
        """
        residential_population = []
        residential_gallons_used = []
        days_in_month = calendar.monthrange(queryset[0].reporting_month.year, queryset[0].reporting_month.month)
        for result in queryset:
            residential_population.append(result.total_population_served)
            if result.units.upper() == "G":
                tmp = result.calculated_production_monthly_gallons_month_2014 * result.percent_residential_use
                residential_gallons_used.append(tmp)
            elif result.units.upper() == "MG":
                tmp = result.calculated_production_monthly_gallons_month_2014 * result.percent_residential_use
                residential_gallons_used.append(tmp)
            elif result.units.upper() == "CCF":
                tmp = result.calculated_production_monthly_gallons_month_2014 * result.percent_residential_use
                residential_gallons_used.append(tmp)
            elif result.units.upper() == "AF":
                tmp = result.calculated_production_monthly_gallons_month_2014 * result.percent_residential_use
                residential_gallons_used.append(tmp)
            else:
                tmp = result.calculated_production_monthly_gallons_month_2014 * result.percent_residential_use
                residential_gallons_used.append(tmp)
        res_gallons = int(sum(residential_gallons_used))
        total_pop = int(sum(residential_population))
        output = (res_gallons / total_pop) / days_in_month[1]
        return output


    def _get_last_year_avg_rgcpd(self, queryset):
        """
        get the average residential gallons per capita per day for last year for suppliers in a queryset
        """
        residential_population = []
        residential_gallons_used = []
        days_in_month = calendar.monthrange(queryset[0].reporting_month.year, queryset[0].reporting_month.month)
        for result in queryset:
            residential_population.append(result.total_population_served)
            if result.units.upper() == "G":
                tmp = result.calculated_production_monthly_gallons_month_2013 * result.percent_residential_use
                residential_gallons_used.append(tmp)
            elif result.units.upper() == "MG":
                tmp = result.calculated_production_monthly_gallons_month_2013 * result.percent_residential_use
                residential_gallons_used.append(tmp)
            elif result.units.upper() == "CCF":
                tmp = result.calculated_production_monthly_gallons_month_2013 * result.percent_residential_use
                residential_gallons_used.append(tmp)
            elif result.units.upper() == "AF":
                tmp = result.calculated_production_monthly_gallons_month_2013 * result.percent_residential_use
                residential_gallons_used.append(tmp)
            else:
                tmp = result.calculated_production_monthly_gallons_month_2013 * result.percent_residential_use
                residential_gallons_used.append(tmp)
        res_gallons = int(sum(residential_gallons_used))
        total_pop = int(sum(residential_population))
        output = (res_gallons / total_pop) / days_in_month[1]
        return output


    def calculate_production_threshold(self, reduction, amount):
        reduce_by = amount * reduction
        output = amount - reduce_by
        return output


    def calculate_values_range(self, min_value, max_value):
        output = max_value - min_value
        return output


    def pct_value_inside_arbitrary_range(self, starting_value, min_value, max_value):
        """
        how to calculate percentage of value inside arbitrary range
        http://math.stackexchange.com/questions/51509/how-to-calculate-percentage-of-value-inside-arbitrary-range
        """
        range_values = max_value - min_value
        distribution_percent = (starting_value - min_value) / range_values
        distribution_percent = distribution_percent * 100
        output = round(distribution_percent, 2)
        return output


    def _create_cumulative_savings(self, current_usage_list, baseline_usage_list, reduction_target, supplier_slug):
        """
        calculate how much a water agency has saved over the first go-round of enforcement
        """
        if None in baseline_usage_list:
            logger.debug("We lack baseline production figures for %s" % (supplier_slug))
            cumulative_calcs = None
        else:
            reduction_target_as_str = format(reduction_target * 100, '.0f')
            cum_current = sum(current_usage_list)
            cum_baseline = sum(baseline_usage_list)
            cum_percent_change = calculate.percentage_change(cum_baseline, cum_current)
            cumulative_calcs = {
                "supplier_slug": supplier_slug,
                "cum_baseline": cum_baseline,
                "cum_current": cum_current,
                "cum_percent_change": cum_percent_change,
                "reduction_target_as_str": reduction_target_as_str,
                "reduction_target": reduction_target
            }
            if cumulative_calcs["cum_percent_change"] < 0:
                cumulative_calcs["cum_status"] = "decreased"
                cumulative_calcs["cum_savings"] = abs(cumulative_calcs["cum_percent_change"])
                cumulative_calcs["cum_increase"] = None
                cumulative_calcs["percent_of_target"] = (cumulative_calcs["cum_savings"] / cumulative_calcs["reduction_target"])
                cumulative_calcs["points_within_target"] = (cumulative_calcs["cum_savings"] - (cumulative_calcs["reduction_target"]) * 100)
                if cumulative_calcs["percent_of_target"] >= 100:
                    cumulative_calcs["cum_success"] = True
                    cumulative_calcs["cum_output"] = "achieving"
                    cumulative_calcs["cum_html"] = "<span style='color: green';>&#x2714;</span>"
                elif cumulative_calcs["percent_of_target"] >= 95:
                    cumulative_calcs["cum_success"] = False
                    cumulative_calcs["cum_output"] = "narrowly missed"
                    cumulative_calcs["cum_html"] = "<span style='color: #8F8F00; font-size: 14px;'>&#x2794;</span>"
                else:
                    cumulative_calcs["cum_success"] = False
                    cumulative_calcs["cum_output"] = "failed to meet"
                    cumulative_calcs["cum_html"] = "<span style='color: red';>&#x2718;</span>"
            # use increased
            elif cumulative_calcs["cum_percent_change"] > 0:
                cumulative_calcs["cum_status"] = "increased"
                cumulative_calcs["cum_savings"] = None
                cumulative_calcs["cum_increase"] = abs(cumulative_calcs["cum_percent_change"])
                cumulative_calcs["percent_of_target"] = (cumulative_calcs["cum_savings"] / cumulative_calcs["reduction_target"])
                cumulative_calcs["points_within_target"] = (cumulative_calcs["cum_savings"] - (cumulative_calcs["reduction_target"]) * 100)
                cumulative_calcs["cum_success"] = False
                cumulative_calcs["cum_output"] = "increased consumption"
                cumulative_calcs["cum_html"] = "<span style='color: red';>&#x2718;</span>"
            # didn't change
            else:
                cumulative_calcs["cum_status"] = "remained flat"
                cumulative_calcs["cum_savings"] = None
                cumulative_calcs["cum_usage"] = None
                cumulative_calcs["percent_of_target"] = (cumulative_calcs["cum_savings"] / cumulative_calcs["reduction_target"])
                cumulative_calcs["points_within_target"] = (cumulative_calcs["cum_savings"] - (cumulative_calcs["reduction_target"]) * 100)
                cumulative_calcs["cum_success"] = False
                cumulative_calcs["cum_output"] = "remained flat"
                cumulative_calcs["cum_html"] = "<span style='color: red';>&#x2718;</span>"

            # print "%s - %s" % (cumulative_calcs["supplier_slug"], format(cumulative_calcs["cum_savings"], '.2f'))

        return cumulative_calcs
