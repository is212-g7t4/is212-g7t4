/*
 * ConnectSphere — C3 Component diagram (Structurizr DSL)
 *
 * Zooms into the API Application container from the C2 diagram (c2.dsl)
 * and shows one component per atomic service from the "MS architecture"
 * frames on the Miro board (composite-flow diagrams + "Master SOA
 * Overview") and this repo's docs (docs/microservices-catalog.md,
 * docs/microservices-diagram-notes.md, INDEX.md).
 *
 * The composite/orchestration services are not drawn as separate
 * boxes — their workflow logic is folded into a relationship owned by
 * whichever atomic component holds the resulting record (e.g. the
 * venue-booking workflow is owned by Venue Availabilities Module, and
 * the safety-check workflow by Safety Check Module).
 *
 * Notifications are in-app only: the Notification Module stores them and
 * the Front-End polls for them. The Hold Checker is a separate container
 * (see c2.dsl) that is only a timer: it triggers the Venue Availabilities
 * Module, which expires the holds and publishes the reminders itself.
 */

workspace "ConnectSphere" "C3 — API Application Components" {

    !identifiers hierarchical

    model {

        # ---- External systems referenced by components below ----
        supabase = softwareSystem "Supabase" "Stores user accounts and relational data for the backend." "External System"
        mongodb  = softwareSystem "MongoDB Atlas" "Stores unstructured forum/communication records." "External System"

        connectSphere = softwareSystem "ConnectSphere" "Event Planning and Venue Booking System." "ConnectSphere System" {

            frontEndApp = container "Front-End App" "GUI for submitting, reviewing, and managing events, bookings, registrations, and safety checks." "React, TypeScript, Vite" "Web Application"

            apiApplication = container "API Application" "Backend REST API handling event, venue, equipment, registration, and safety-check business logic." "Python, Flask" "Backend Application" {

                # one component per atomic service — composite/orchestration logic is
                # folded into relationships owned by the atomic component that holds
                # the resulting record (see relationships below)
                userModule                  = component "User Module" "Owns user accounts, roles (including Event Coordinator Lead and Safety Officer), and login/JWT issuance." "Python module" "Atomic Module"
                eventModule                 = component "Event Module" "Owns the Event entity and coordinates assignment (queue, assign, reassign), change/cancellation, and status workflows. Only a safety approval sets Approved." "Python module" "Atomic Module"
                venueModule                 = component "Venue Module" "Owns the venue catalogue (including setup/turnaround times and safety information) and the suitability-check computation." "Python module" "Atomic Module"
                venueAvailabilitiesModule   = component "Venue Availabilities Module" "Owns venue booking, hold, and closure records and coordinates the venue-booking workflow, including buffer-aware conflict checks." "Python module" "Atomic Module"
                equipmentModule             = component "Equipment Module" "Owns the equipment catalogue only — no reservation data." "Python module" "Atomic Module"
                equipmentAvailabilityModule = component "Equipment Availability Module" "Owns equipment reservation records and coordinates the equipment-reservation workflow, including re-review and release." "Python module" "Atomic Module"
                registrationModule          = component "Registration Module" "Owns attendee registration records and coordinates the attendee registration/withdrawal workflow." "Python module" "Atomic Module"
                safetyCheckModule           = component "Safety Check Module" "Owns safety check records and coordinates the safety-check workflow: submit, review, decide, resubmit." "Python module" "Atomic Module"
                notificationModule          = component "Notification Module" "Owns in-app notification records, consumes notification events from the broker, and serves them to the Front-End." "Python module" "Atomic Module"
                forumModule                 = component "Forum / Communication Module" "Owns all communication tied to a request, such as clarifications and decision reasons." "Python module" "Atomic Module NoSQL"
            }

            holdChecker = container "Hold Checker" "Runs every minute and asks the API to expire holds that have run out and to send the 3-day reminder. Holds no logic or data of its own." "Python scheduled job" "Background Job"

            messageBroker = container "Message Broker" "The only asynchronous path in the system — modules publish notification events here; the Notification Module consumes them." "RabbitMQ" "Message Broker"
        }

        # ================= Relationships =================

        # Front-End App -> entry-point modules
        connectSphere.frontEndApp -> connectSphere.apiApplication.userModule "Logs in and loads user roles using" "HTTPS/JSON"
        connectSphere.frontEndApp -> connectSphere.apiApplication.eventModule "Creates/edits/cancels events, views the unassigned queue, and assigns/reassigns coordinators, using" "HTTPS/JSON"
        connectSphere.frontEndApp -> connectSphere.apiApplication.venueModule "Manages venue profiles, setup/turnaround times, and safety information using" "HTTPS/JSON"
        connectSphere.frontEndApp -> connectSphere.apiApplication.venueAvailabilitiesModule "Submits & manages venue bookings, holds, and closures using" "HTTPS/JSON"
        connectSphere.frontEndApp -> connectSphere.apiApplication.equipmentModule "Lists and adds equipment catalogue records using" "HTTPS/JSON"
        connectSphere.frontEndApp -> connectSphere.apiApplication.equipmentAvailabilityModule "Submits & manages equipment requests using" "HTTPS/JSON"
        connectSphere.frontEndApp -> connectSphere.apiApplication.registrationModule "Registers/withdraws attendees using" "HTTPS/JSON"
        connectSphere.frontEndApp -> connectSphere.apiApplication.safetyCheckModule "Submits, reviews, and decides safety checks using" "HTTPS/JSON"
        connectSphere.frontEndApp -> connectSphere.apiApplication.notificationModule "Polls for and marks-read in-app notifications using" "HTTPS/JSON"

        # Event Module — owns coordinator-assignment + change/cancellation workflows
        connectSphere.apiApplication.eventModule -> connectSphere.apiApplication.userModule "Looks up eligible coordinators (including the Lead) from (coordinator assignment)"
        connectSphere.apiApplication.eventModule -> connectSphere.apiApplication.equipmentAvailabilityModule "Re-checks or releases equipment commitments via (event change/cancellation)"
        connectSphere.apiApplication.eventModule -> connectSphere.apiApplication.equipmentModule "Reads equipment catalogue details from (event change/cancellation)"
        connectSphere.apiApplication.eventModule -> connectSphere.apiApplication.venueAvailabilitiesModule "Releases venue bookings via (event cancellation)"
        connectSphere.apiApplication.eventModule -> connectSphere.apiApplication.forumModule "Logs assignment/change/cancellation reasons to"
        connectSphere.apiApplication.eventModule -> connectSphere.messageBroker "Publishes coordinator-assigned/removed & event-changed notifications to" "AMQP (async)"

        # Venue Availabilities Module — owns the venue-booking workflow (bookings, holds, closures)
        connectSphere.apiApplication.venueAvailabilitiesModule -> connectSphere.apiApplication.eventModule "Reads event details and the assigned coordinator from"
        connectSphere.apiApplication.venueAvailabilitiesModule -> connectSphere.apiApplication.venueModule "Checks venue suitability and reads setup/turnaround times via"
        connectSphere.apiApplication.venueAvailabilitiesModule -> connectSphere.apiApplication.forumModule "Logs the approval/rejection reason to"
        connectSphere.apiApplication.venueAvailabilitiesModule -> connectSphere.messageBroker "Publishes booking-decision, closure-affected-booking & hold-expiry/3-day-reminder notifications to" "AMQP (async)"

        # Equipment Availability Module — owns the equipment-reservation workflow
        connectSphere.apiApplication.equipmentAvailabilityModule -> connectSphere.apiApplication.eventModule "Reads event details from"
        connectSphere.apiApplication.equipmentAvailabilityModule -> connectSphere.apiApplication.equipmentModule "Reads equipment catalogue details from"
        connectSphere.apiApplication.equipmentAvailabilityModule -> connectSphere.apiApplication.forumModule "Logs the approval/rejection reason to"
        connectSphere.apiApplication.equipmentAvailabilityModule -> connectSphere.messageBroker "Publishes equipment-decision notifications to" "AMQP (async)"

        # Registration Module — owns the attendee registration/withdrawal workflow
        connectSphere.apiApplication.registrationModule -> connectSphere.apiApplication.eventModule "Validates the event is open for registration via"
        connectSphere.apiApplication.registrationModule -> connectSphere.messageBroker "Publishes registration-confirmed notifications to" "AMQP (async)"

        # Safety Check Module — owns the safety-check workflow
        connectSphere.apiApplication.safetyCheckModule -> connectSphere.apiApplication.eventModule "Reads event details from, and sets event status via"
        connectSphere.apiApplication.safetyCheckModule -> connectSphere.apiApplication.venueAvailabilitiesModule "Checks approval of, and reopens flagged, venue bookings via"
        connectSphere.apiApplication.safetyCheckModule -> connectSphere.apiApplication.equipmentAvailabilityModule "Checks approval of, and reopens flagged, equipment requests via"
        connectSphere.apiApplication.safetyCheckModule -> connectSphere.apiApplication.venueModule "Reads capacity, layout, emergency access and restrictions from"
        connectSphere.apiApplication.safetyCheckModule -> connectSphere.apiApplication.userModule "Looks up Safety Officers from (notifications)"
        connectSphere.apiApplication.safetyCheckModule -> connectSphere.apiApplication.forumModule "Logs safety decision reasons to"
        connectSphere.apiApplication.safetyCheckModule -> connectSphere.messageBroker "Publishes safety-check submitted & decision notifications to" "AMQP (async)"

        # Notification Module — consumes the broker, stores in-app notifications for polling
        connectSphere.apiApplication.notificationModule -> connectSphere.messageBroker "Consumes notification events from" "AMQP (async)"

        # Hold Checker — separate container; only a timer that triggers the API (no broker or database access of its own)
        connectSphere.holdChecker -> connectSphere.apiApplication.venueAvailabilitiesModule "Every minute, triggers hold expiry and the 3-day reminder check on" "HTTPS/JSON"

        # Atomic modules -> data stores (cloud-hosted, outside the system boundary)
        connectSphere.apiApplication.userModule -> supabase "Authenticates users & reads/writes accounts in" "HTTPS/SQL"
        connectSphere.apiApplication.eventModule -> supabase "Reads/writes event and assignment records in" "HTTPS/SQL"
        connectSphere.apiApplication.venueModule -> supabase "Reads/writes venue catalogue in" "HTTPS/SQL"
        connectSphere.apiApplication.venueAvailabilitiesModule -> supabase "Reads/writes booking, hold, and closure records in" "HTTPS/SQL"
        connectSphere.apiApplication.equipmentModule -> supabase "Reads/writes equipment catalogue in" "HTTPS/SQL"
        connectSphere.apiApplication.equipmentAvailabilityModule -> supabase "Reads/writes reservation records in" "HTTPS/SQL"
        connectSphere.apiApplication.registrationModule -> supabase "Reads/writes registration records in" "HTTPS/SQL"
        connectSphere.apiApplication.safetyCheckModule -> supabase "Reads/writes safety check records in" "HTTPS/SQL"
        connectSphere.apiApplication.notificationModule -> supabase "Reads/writes notification records in" "HTTPS/SQL"
        connectSphere.apiApplication.forumModule -> mongodb "Reads/writes communication entries in" "TCP"
    }

    views {

        component connectSphere.apiApplication "C3-ApiApplication" {
            include *
            autoLayout tb
            title "API Application — Components (C3)"
        }

        styles {
            element "External System" {
                background #999999
                color #ffffff
                shape cylinder
            }
            element "ConnectSphere System" {
                background #ffffff
                color #1a1a1a
            }
            element "Web Application" {
                background #305bab
                color #ffffff
                shape webBrowser
            }
            element "Backend Application" {
                background #438dd5
                color #ffffff
            }
            element "Background Job" {
                background #85bbf0
                color #000000
            }
            element "Atomic Module" {
                background #ffdc4a
                color #1a1a1a
                shape component
                width 500
                height 360
            }
            element "NoSQL" {
                stroke #087429
            }
            element "Message Broker" {
                background #dedaff
                color #6631d7
                shape pipe
            }
            element "Component" {
                background #85bbf0
                color #000000
                shape component
            }
            relationship "Relationship" {
                routing Orthogonal
            }
        }
    }
}