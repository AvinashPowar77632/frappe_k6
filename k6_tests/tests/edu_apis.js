/**
 * Frappe Education (EDU) specific API tests.
 * Covers: Student, Program, Course, Student Applicant, Fee Structure,
 *         Assessment Plan, Academic Year, Student Group, etc.
 */

import { group } from "k6";
import { getList, callMethod, thinkTime } from "../utils/helpers.js";

export function eduApiTests(baseUrl, headers) {
  group("EDU: Academic Year", () => {
    getList(baseUrl, "Academic Year", headers);
    thinkTime();
  });

  group("EDU: Program", () => {
    getList(baseUrl, "Program", headers);
    thinkTime();
  });

  group("EDU: Course", () => {
    getList(baseUrl, "Course", headers, { limit: 50 });
    thinkTime();
  });

  group("EDU: Student", () => {
    getList(baseUrl, "Student", headers, { limit: 20 });
    thinkTime();
  });

  group("EDU: Student Applicant", () => {
    getList(baseUrl, "Student Applicant", headers, { limit: 20 });
    thinkTime();
  });

  group("EDU: Student Group", () => {
    getList(baseUrl, "Student Group", headers);
    thinkTime();
  });

  group("EDU: Fee Structure", () => {
    getList(baseUrl, "Fee Structure", headers);
    thinkTime();
  });

  group("EDU: Assessment Plan", () => {
    getList(baseUrl, "Assessment Plan", headers, { limit: 20 });
    thinkTime();
  });

  group("EDU: Instructor", () => {
    getList(baseUrl, "Instructor", headers);
    thinkTime();
  });

  group("EDU: Course Schedule", () => {
    getList(baseUrl, "Course Schedule", headers, { limit: 20 });
    thinkTime();
  });

  group("EDU: Guardian", () => {
    getList(baseUrl, "Guardian", headers, { limit: 20 });
    thinkTime();
  });
}

export function eduMethodTests(baseUrl, headers) {
  group("EDU Method: Get Program Enrollment List", () => {
    callMethod(
      baseUrl,
      "frappe.client.get_list",
      {
        doctype: "Program Enrollment",
        fields: ["name", "student", "program", "academic_year"],
        limit: 10,
      },
      headers
    );
    thinkTime();
  });

  group("EDU Method: Get Fee Schedule", () => {
    callMethod(
      baseUrl,
      "frappe.client.get_list",
      {
        doctype: "Fee Schedule",
        fields: ["name", "program", "academic_year", "total_amount"],
        limit: 10,
      },
      headers
    );
    thinkTime();
  });

  group("EDU Method: Get Assessment Result", () => {
    callMethod(
      baseUrl,
      "frappe.client.get_list",
      {
        doctype: "Assessment Result",
        fields: ["name", "student", "assessment_plan", "total_score"],
        limit: 10,
      },
      headers
    );
    thinkTime();
  });
}
