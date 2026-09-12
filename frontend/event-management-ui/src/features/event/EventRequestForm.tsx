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

interface FormErrors {
  eventName?: string
  description?: string
  purpose?: string
  preferredStartDate?: string
  preferredEndDate?: string
  expectedAttendance?: string
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
  const [errors, setErrors] = useState<FormErrors>({})

  const [missingFields, setMissingFields] = useState<string[]>([])
  const [showMissingFieldsPopup, setShowMissingFieldsPopup] = useState(false)
  const validateForm = (): boolean => {
  const newErrors: FormErrors = {}
  const newMissingFields: string[] = []

  // Event Name
  if (!formData.eventName.trim()) {
    newErrors.eventName = 'Event Name is required.'
    newMissingFields.push('Event Name')
  }

  // Description
  if (!formData.description.trim()) {
    newErrors.description = 'Description is required.'
    newMissingFields.push('Description')
  }

  // Purpose
  if (!formData.purpose.trim()) {
    newErrors.purpose = 'Purpose is required.'
    newMissingFields.push('Purpose')
  }

  // Start Date
  if (!formData.preferredStartDate) {
    newErrors.preferredStartDate =
      'Preferred Start Date & Time is required.'

    newMissingFields.push('Preferred Start Date & Time')
  }

  // End Date
  if (!formData.preferredEndDate) {
    newErrors.preferredEndDate =
      'Preferred End Date & Time is required.'

    newMissingFields.push('Preferred End Date & Time')
  }

  // Expected Attendance
  if (!formData.expectedAttendance) {
    newErrors.expectedAttendance =
      'Expected Attendance is required.'

    newMissingFields.push('Expected Attendance')
  } else if (Number(formData.expectedAttendance) <= 0) {
    newErrors.expectedAttendance =
      'Expected Attendance must be greater than 0.'
  }

  // Date validation
  if (
    formData.preferredStartDate &&
    formData.preferredEndDate &&
    new Date(formData.preferredEndDate) <
      new Date(formData.preferredStartDate)
  ) {
    newErrors.preferredEndDate =
      'End date and time cannot be before the start date and time.'
  }

  setErrors(newErrors)
  setMissingFields(newMissingFields)

  if (newMissingFields.length > 0) {
    setShowMissingFieldsPopup(true)
  }

  return Object.keys(newErrors).length === 0
}

  const handleChange = (
  event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
) => {
  const { name, value } = event.target

  setFormData((previousData) => ({
    ...previousData,
    [name]: value,
  }))

  setErrors((previousErrors) => ({
    ...previousErrors,
    [name]: undefined,
  }))
}

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
  event.preventDefault()

  const isValid = validateForm()

  if (!isValid) {
    return
  }

  console.log('Form is valid:', formData)

}

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

              {errors.eventName && (
              <span className="error-message">
                {errors.eventName}
              </span>
            )}
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
              {errors.description && (
              <span className="error-message">
                {errors.description}
              </span>
              )}
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
              {errors.purpose && (
                <span className="error-message">
                  {errors.purpose}
                </span>
              )}
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
                {errors.preferredStartDate && (
                  <span className="error-message">
                    {errors.preferredStartDate}
                  </span>
                )}
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

                {errors.preferredEndDate && (
                  <span className="error-message">
                    {errors.preferredEndDate}
                  </span>
                )}
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
              {errors.expectedAttendance && (
                <span className="error-message">
                  {errors.expectedAttendance}
                </span>
              )}
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
       {showMissingFieldsPopup && (
      <div className="validation-popup-overlay">
        <div className="validation-popup">
          <div className="validation-popup-header">
            <h2>Missing Required Fields</h2>

            <button
              type="button"
              className="validation-popup-close"
              onClick={() => setShowMissingFieldsPopup(false)}
              aria-label="Close"
            >
              ×
            </button>
          </div>

          <p>
            Please complete the following required fields before
            submitting your event request:
          </p>

          <ul className="missing-fields-list">
            {missingFields.map((field) => (
              <li key={field}>{field}</li>
            ))}
          </ul>

          <div className="validation-popup-actions">
            <button
              type="button"
              className="validation-popup-button"
              onClick={() => setShowMissingFieldsPopup(false)}
            >
              Back to Form
            </button>
          </div>
        </div>
      </div>
    )}
    </div>
  );
}

export default EventRequestForm;