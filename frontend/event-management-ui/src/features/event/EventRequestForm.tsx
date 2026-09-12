import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import "./EventRequestForm.css";

interface EventFormData {
  eventName: string;
  description: string;
  purpose: string;
  preferredStartDate: string;
  preferredEndDate: string;
  expectedAttendance: string;
  venueRequirements: string;
  accessibilityNeeds: string;
  equipmentRequirements: string;
  registrationNeeds: string;
}

function EventRequestForm() {
  const [formData, setFormData] = useState<EventFormData>({
    eventName: "",
    description: "",
    purpose: "",
    preferredStartDate: "",
    preferredEndDate: "",
    expectedAttendance: "",
    venueRequirements: "",
    accessibilityNeeds: "",
    equipmentRequirements: "",
    registrationNeeds: "",
  });

  const handleChange = (
    event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
  ) => {
    const { name, value } = event.target;

    setFormData((previousData) => ({
      ...previousData,
      [name]: value,
    }));
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    console.log(formData);
  };

  return (
    <div className="event-request-page">
      <div className="event-request-container">
        <div className="event-request-header">
          <h1>Create Event Request</h1>

          <p>
            Provide the preliminary details and requirements for your event.
            ConnectSphere will review your request after submission.
          </p>
        </div>

        <form className="event-request-form" onSubmit={handleSubmit}>
          <section className="form-section">
            <div className="section-header">
              <h2>Event Information</h2>
              <p>Tell us about the event you would like to organise.</p>
            </div>

            <div className="form-group">
              <label htmlFor="eventName">
                Event Name <span className="required">*</span>
              </label>

              <input
                id="eventName"
                name="eventName"
                type="text"
                value={formData.eventName}
                onChange={handleChange}
                placeholder="e.g. Southeast Asia Technology Conference"
              />
            </div>

            <div className="form-group">
              <label htmlFor="description">
                Description <span className="required">*</span>
              </label>

              <textarea
                id="description"
                name="description"
                value={formData.description}
                onChange={handleChange}
                placeholder="Provide a brief description of the event."
                rows={5}
              />
            </div>

            <div className="form-group">
              <label htmlFor="purpose">
                Purpose <span className="required">*</span>
              </label>

              <textarea
                id="purpose"
                name="purpose"
                value={formData.purpose}
                onChange={handleChange}
                placeholder="What is the main purpose or objective of this event?"
                rows={4}
              />
            </div>
          </section>

          <section className="form-section">
            <div className="section-header">
              <h2>Date & Attendance</h2>
              <p>
                Provide your preferred event period and estimated number of
                attendees.
              </p>
            </div>

            <div className="form-row">
              <div className="form-group">
                <label htmlFor="preferredStartDate">
                  Preferred Start Date & Time{" "}
                  <span className="required">*</span>
                </label>

                <input
                  id="preferredStartDate"
                  name="preferredStartDate"
                  type="datetime-local"
                  value={formData.preferredStartDate}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label htmlFor="preferredEndDate">
                  Preferred End Date & Time{" "}
                  <span className="required">*</span>
                </label>

                <input
                  id="preferredEndDate"
                  name="preferredEndDate"
                  type="datetime-local"
                  value={formData.preferredEndDate}
                  onChange={handleChange}
                />
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="expectedAttendance">
                Expected Attendance <span className="required">*</span>
              </label>

              <input
                id="expectedAttendance"
                name="expectedAttendance"
                type="number"
                min="1"
                value={formData.expectedAttendance}
                onChange={handleChange}
                placeholder="e.g. 150"
              />
            </div>
          </section>

          <section className="form-section">
            <div className="section-header">
              <h2>Event Requirements</h2>

              <p>
                Provide any additional requirements that may help ConnectSphere plan your
                event. These fields are optional.
              </p>
            </div>

            <div className="form-group">
              <label htmlFor="venueRequirements">
                Venue Requirements
                <span className="optional"> Optional</span>
              </label>

              <textarea
                id="venueRequirements"
                name="venueRequirements"
                value={formData.venueRequirements}
                onChange={handleChange}
                placeholder="e.g. Theatre-style room, stage area and breakout space."
                rows={4}
              />
            </div>

            <div className="form-group">
              <label htmlFor="accessibilityNeeds">
                Accessibility Needs
                <span className="optional"> Optional</span>
              </label>

              <textarea
                id="accessibilityNeeds"
                name="accessibilityNeeds"
                value={formData.accessibilityNeeds}
                onChange={handleChange}
                placeholder="e.g. Wheelchair-accessible venue."
                rows={4}
              />
            </div>

            <div className="form-group">
              <label htmlFor="equipmentRequirements">
                Equipment Requirements
                <span className="optional"> Optional</span>
              </label>

              <textarea
                id="equipmentRequirements"
                name="equipmentRequirements"
                value={formData.equipmentRequirements}
                onChange={handleChange}
                placeholder="e.g. Projector and two wireless microphones."
                rows={4}
              />
            </div>

            <div className="form-group">
              <label htmlFor="registrationNeeds">
                Registration Needs
                <span className="optional"> Optional</span>
              </label>

              <textarea
                id="registrationNeeds"
                name="registrationNeeds"
                value={formData.registrationNeeds}
                onChange={handleChange}
                placeholder="e.g. Attendee registration is required."
                rows={4}
              />
            </div>
          </section>

          <div className="form-footer">
            <p className="required-note">
              <span className="required">*</span> Required fields
            </p>

            <div className="form-actions">
              <button type="button" className="secondary-button">
                Cancel
              </button>

              <button type="submit" className="primary-button">
                Submit Request
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

export default EventRequestForm;