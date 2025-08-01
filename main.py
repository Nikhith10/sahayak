"""
API Integration for Parent-Teacher Meeting System
Extends the existing Flask app with student data management endpoints
"""

from flask import Flask, jsonify, request, send_file, send_from_directory, Response
import google.genai as genai
import json
import os
from dotenv import load_dotenv
from typing import Dict, List, Any, Optional, Union, Generator, Tuple

# Import our custom modules - handle optional dependencies
StudentDatabase = None
TalkingPointsGenerator = None
StudentDataGenerator = None
generate_meeting_agenda = None

# Try to import AI talking points (doesn't require Firebase)
try:
    from ai_talking_points import TalkingPointsGenerator, generate_meeting_agenda
    AI_TALKING_POINTS_AVAILABLE = True
    print("✅ AI talking points module loaded")
except ImportError as e:
    print(f"⚠️ AI talking points module not available: {e}")
    AI_TALKING_POINTS_AVAILABLE = False

# Try to import Firebase-dependent modules
try:
    from firestore_integration import StudentDatabase
    FIREBASE_AVAILABLE = True
    print("✅ Firebase integration loaded")
except ImportError as e:
    print(f"⚠️ Firebase integration not available: {e}")
    FIREBASE_AVAILABLE = False

# Try to import data generator (may have its own dependencies)
try:
    from generate_synthetic_data import StudentDataGenerator
    DATA_GENERATOR_AVAILABLE = True
    print("✅ Data generator loaded")
except ImportError as e:
    print(f"⚠️ Data generator not available: {e}")
    DATA_GENERATOR_AVAILABLE = False

load_dotenv()


class StudentMeetingAPI:
    def __init__(self, app: Flask):
        self.app = app

        # Initialize only if modules are available
        self.talking_points_generator = None
        self.data_generator = None

        if AI_TALKING_POINTS_AVAILABLE and TalkingPointsGenerator:
            self.talking_points_generator = TalkingPointsGenerator()
            print("✅ AI talking points generator initialized")
        if DATA_GENERATOR_AVAILABLE and StudentDataGenerator:
            self.data_generator = StudentDataGenerator()
            print("✅ Data generator initialized")

        # Initialize database if Firebase is available
        self.db = None
        if FIREBASE_AVAILABLE and StudentDatabase:
            try:
                self.db = StudentDatabase()
                print("✅ Firestore database connected")
            except Exception as e:
                print(f"⚠️ Firestore connection failed: {e}")
                print("📝 Using local JSON files for data storage")

        self.setup_routes()

    def setup_routes(self):
        """Setup API routes for student management"""

        @self.app.route("/api/students", methods=["GET"])
        def get_students():
            """Get all students or filter by grade/teacher"""
            try:
                grade = request.args.get("grade")
                teacher_id = request.args.get("teacher_id")

                if self.db:
                    if grade:
                        students = self.db.get_students_by_grade(grade)
                    elif teacher_id:
                        students = self.db.get_students_by_teacher(teacher_id)
                    else:
                        # Get all students (limit to 50 for performance)
                        students = self.db.search_students(
                            "metadata.academicYear", "==", "2024-2025")[:50]
                else:
                    # Fallback to local JSON file
                    students = self.load_local_students()
                    if grade:
                        students = [s for s in students if s.get(
                            "personalInfo", {}).get("grade") == grade]

                return jsonify({
                    "success": True,
                    "data": students,
                    "count": len(students)
                })

            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/students/<student_id>", methods=["GET"])
        def get_student(student_id):
            """Get complete student profile including sub-collections"""
            try:
                if self.db:
                    student_data = self.db.get_complete_student_profile(
                        student_id)
                else:
                    # Fallback to local data
                    students = self.load_local_students()
                    student_data = next(
                        (s for s in students if s.get("studentId") == student_id), None)

                if not student_data:
                    return jsonify({"success": False, "error": "Student not found"}), 404

                return jsonify({
                    "success": True,
                    "data": student_data
                })

            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/students/<student_id>/talking-points", methods=["GET"])
        def generate_talking_points(student_id):
            """Generate AI talking points for a specific student"""
            try:
                # Get student data
                if self.db:
                    student_data = self.db.get_complete_student_profile(
                        student_id)
                else:
                    students = self.load_local_students()
                    student_data = next(
                        (s for s in students if s.get("studentId") == student_id), None)

                if not student_data:
                    return jsonify({"success": False, "error": "Student not found"}), 404

                # Generate talking points
                if self.talking_points_generator:
                    talking_points = self.talking_points_generator.generate_talking_points(
                        student_data)
                else:
                    return jsonify({"success": False, "error": "AI talking points module not available"}), 503

                # Generate meeting agenda
                if generate_meeting_agenda:
                    agenda = generate_meeting_agenda(talking_points)
                else:
                    agenda = {
                        "error": "Meeting agenda generation not available"}

                return jsonify({
                    "success": True,
                    "data": {
                        "talking_points": talking_points,
                        "meeting_agenda": agenda,
                        "generated_at": talking_points["meeting_summary"]["meeting_date"]
                    }
                })

            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/students/<student_id>/assessments", methods=["GET", "POST"])
        def handle_assessments(student_id: str) -> Union[Response, Tuple[Response, int]]:
            """Get or add student assessments"""
            if request.method == "GET":
                try:
                    limit = request.args.get("limit", type=int, default=10)

                    if self.db:
                        assessments = self.db.get_student_assessments(
                            student_id, limit)
                    else:
                        # Mock data for local testing
                        assessments = self.generate_mock_assessments(
                            student_id, limit)

                    return jsonify({
                        "success": True,
                        "data": assessments,
                        "count": len(assessments)
                    })

                except Exception as e:
                    return jsonify({"success": False, "error": str(e)}), 500

            elif request.method == "POST":
                try:
                    assessment_data = request.get_json()

                    if self.db:
                        assessment_id = self.db.add_assessment(
                            student_id, assessment_data)
                        return jsonify({
                            "success": True,
                            "data": {"assessment_id": assessment_id}
                        })
                    else:
                        return jsonify({"success": False, "error": "Database not available"}), 503

                except Exception as e:
                    return jsonify({"success": False, "error": str(e)}), 500

            # This should never be reached, but add it for type safety
            return jsonify({"success": False, "error": "Invalid request method"}), 405

        @self.app.route("/api/generate-synthetic-data", methods=["POST"])
        def generate_synthetic_data():
            """Generate synthetic student data"""
            try:
                req_data = request.get_json() or {}
                count = req_data.get("count", 5)
                grade = req_data.get("grade", "5")

                # Generate synthetic data
                if DATA_GENERATOR_AVAILABLE and self.data_generator:
                    students = self.data_generator.generate_multiple_students(
                        count, grade)
                else:
                    return jsonify({"success": False, "error": "Data generator not available"}), 503

                # Save to database if available
                if self.db:
                    doc_ids = self.db.bulk_import_students(students)
                    return jsonify({
                        "success": True,
                        "message": f"Generated and imported {len(students)} students",
                        "data": {"document_ids": doc_ids, "students": students}
                    })
                else:
                    # Save to local file
                    filename = f"synthetic_students_grade_{grade}.json"
                    with open(filename, 'w') as f:
                        json.dump(students, f, indent=2, default=str)

                    return jsonify({
                        "success": True,
                        "message": f"Generated {len(students)} students and saved to {filename}",
                        "data": {"students": students}
                    })

            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/meeting-summary", methods=["POST"])
        def generate_meeting_summary():
            """Generate AI-powered meeting summary using Gemini"""
            try:
                req_data = request.get_json()
                student_id = req_data.get("student_id")
                additional_notes = req_data.get("notes", "")

                if not student_id:
                    return jsonify({"success": False, "error": "student_id is required"}), 400

                # Get student data and talking points
                if self.db:
                    student_data = self.db.get_complete_student_profile(
                        student_id)
                else:
                    students = self.load_local_students()
                    student_data = next(
                        (s for s in students if s.get("studentId") == student_id), None)

                if not student_data:
                    return jsonify({"success": False, "error": "Student not found"}), 404

                if self.talking_points_generator:
                    talking_points = self.talking_points_generator.generate_talking_points(
                        student_data)
                else:
                    return jsonify({"success": False, "error": "AI talking points module not available"}), 503

                # Prepare prompt for Gemini
                first_name = student_data['personalInfo']['firstName']
                last_name = student_data['personalInfo']['lastName']
                grade = student_data['personalInfo']['grade']

                prompt = f"""
As an experienced teacher, create a comprehensive parent-teacher meeting summary for:
Student: {first_name} {last_name} (Grade {grade})

Student Data Summary:
- Current GPA: {student_data.get('academicProfile', {}).get('currentGPA', 'N/A')}
- Attendance Rate: {student_data.get('behavioralProfile', {}).get('attendance', {}).get('attendanceRate', 'N/A')}
- Learning Style: {student_data.get('academicProfile', {}).get('learningStyle', 'N/A')}
- Participation Level: {student_data.get('behavioralProfile', {}).get('participation', {}).get('level', 'N/A')}

Key Talking Points:
{json.dumps(talking_points['talking_points_by_category'], indent=2)}

Additional Teacher Notes: {additional_notes}

Please create:
1. A warm, professional meeting summary
2. Key strengths to celebrate
3. Areas for growth with specific strategies
4. Action items for parents and teacher
5. Next steps and follow-up timeline

Keep the tone positive, constructive, and focused on the student's success.
"""

                # Use existing Gemini integration
                API_KEY = os.environ.get('GOOGLE_GENAI_API_KEY')
                if not API_KEY or API_KEY == 'TODO':
                    return jsonify({"success": False, "error": "Gemini API key not configured"}), 500

                ai = genai.Client(api_key=API_KEY)

                contents = [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}]
                    }
                ]

                response = ai.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=contents  # type: ignore
                )

                return jsonify({
                    "success": True,
                    "data": {
                        "meeting_summary": response.text,
                        "student_info": {
                            "name": f"{first_name} {last_name}",
                            "grade": grade,
                            "student_id": student_id
                        },
                        "talking_points": talking_points,
                        "generated_at": talking_points["meeting_summary"]["meeting_date"]
                    }
                })

            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500

    def load_local_students(self) -> List[Dict[str, Any]]:
        """Load students from local JSON file as fallback"""
        try:
            with open("synthetic_students.json", "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return []

    def generate_mock_assessments(self, student_id: str, limit: int) -> List[Dict[str, Any]]:
        """Generate mock assessment data for testing"""
        if self.data_generator:
            return self.data_generator.generate_assessments(student_id, limit)
        else:
            # Return mock data if generator not available
            return [
                {
                    "id": f"mock_{i}",
                    "student_id": student_id,
                    "subject": "Math",
                    "score": 85,
                    "date": "2024-01-01"
                } for i in range(limit)
            ]

# Update your existing main.py to include these new endpoints


def create_enhanced_app():
    """Create Flask app with enhanced student management features"""

    API_KEY = os.environ.get('GOOGLE_GENAI_API_KEY', 'TODO')
    if not API_KEY:
        raise ValueError(
            "API key not found. Please set the GOOGLE_GENAI_API_KEY environment variable.")

    ai = genai.Client(api_key=API_KEY)
    app = Flask(__name__)

    # Original routes
    @app.route("/")
    def index():
        return send_file('web/index.html')

    @app.route("/api/generate", methods=["POST"])
    def generate_api() -> Union[Response, Tuple[Generator[str, None, None], Dict[str, str]]]:
        if request.method == "POST":
            if not API_KEY or API_KEY == 'TODO':
                return jsonify({"error": '''
                    To get started, get an API key at
                    https://g.co/ai/idxGetGeminiKey and enter it in
                    main.py
                    '''.replace('\n', '')})
            try:
                req_body = request.get_json()
                contents = req_body.get("contents")
                response = ai.models.generate_content_stream(
                    model=req_body.get("model"), contents=contents)

                def stream() -> Generator[str, None, None]:
                    for chunk in response:
                        yield 'data: %s\n\n' % json.dumps({"text": chunk.text})

                return stream(), {'Content-Type': 'text/event-stream'}

            except Exception as e:
                return jsonify({"error": str(e)})

        # This should never be reached, but add it for type safety
        return jsonify({"error": "Invalid request method"})

    @app.route('/<path:path>')
    def static_files(path):
        return send_from_directory('web', path)

    # Add student management API
    student_api = StudentMeetingAPI(app)

    return app

    @app.route("/api/generate_mermaid", methods=["POST"])
    def generate_mermaid():
        data = request.json
        prompt = data.get("prompt")

        if not prompt:
            return jsonify({"error": "No prompt provided"}), 400

        system_prompt = """
    You are a Mermaid diagram expert. Convert natural language descriptions into valid Mermaid diagram syntax.

    CRITICAL RULES:
    1. Return ONLY the Mermaid code, no explanations or markdown formatting
    2. Start directly with the diagram type (flowchart, sequenceDiagram, etc.)
    3. Use proper Mermaid syntax - NEVER use semicolons (;) in flowcharts
    4. Make the diagram clear and well-structured
    5. Each edge must be on a new line
    6. Avoid malformed connections
    """

        full_prompt = f"{system_prompt}\n\nUser request: \"{prompt}\"\n\nMermaid diagram:"

        try:
            response = ai.models.generate_content(
                model="gemini-1.5-flash",
                contents=[{"role": "user", "parts": [{"text": full_prompt}]}]
            )

            text = response.text.strip() if response.text else ""
            text = (
                text.replace("```mermaid", "")
                    .replace("```", "")
                    .replace(";", "")
                    .strip()
            )
            text = text.replace("]B -->", "]\nB -->")

            return jsonify({"diagram": text})

        except Exception as e:
            print("Error in generate_mermaid:", e)  # Debug log
            return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app = create_enhanced_app()
    print("🚀 Enhanced Sahayak API with Parent-Teacher Meeting features starting...")
    print("📚 Available endpoints:")
    print("   GET  /api/students - List all students")
    print("   GET  /api/students/<id> - Get student details")
    print("   GET  /api/students/<id>/talking-points - Generate AI talking points")
    print("   POST /api/generate-synthetic-data - Generate test data")
    print("   POST /api/meeting-summary - Generate AI meeting summary")
    app.run(debug=True, port=5000)
