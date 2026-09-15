/*
 * ConnectSphere — C3 Component diagram (Structurizr DSL)
 *
 * Zooms into the API Application container from the C2 diagram (c2.dsl)
 * and shows one component per atomic service from the "MS architecture"
 * frames on the Miro board (five composite-flow diagrams + "Master SOA
 * Overview") and this repo's docs (docs/microservices-catalog.md,
 * docs/microservices-diagram-notes.md, INDEX.md).
 *
 * The five composite/orchestration services are not drawn as separate
 * boxes — their workflow logic is folded into a relationship owned by
 * whichever atomic component holds the resulting record (e.g. the
 * venue-booking workflow is owned by Venue Availabilities Module).
 */

workspace "ConnectSphere" "C3 — API Application Components" {

    !identifiers hierarchical

    model {

        # ---- External systems referenced by components below ----
        supabase = softwareSystem "Supabase" "Stores user accounts and relational data for the backend." "External System"
        mongodb  = softwareSystem "MongoDB Atlas" "Stores unstructured forum/communication records." "External System"
        emailProvider = softwareSystem "Notification Service" "External service for sending email/SMS alerts." "External System"

        connectSphere = softwareSystem "ConnectSphere" "Event Planning and Venue Booking System." "ConnectSphere System" {

            frontEndApp = container "Front-End App" "GUI for submitting, reviewing, and managing events, bookings, and registrations." "React, TypeScript, Vite" "Web Application"

            apiApplication = container "API Application" "Backend REST API handling event, venue, equipment, and registration business logic." "Python, Flask" "Backend Application" {

                # one component per atomic service — composite/orchestration logic is
                # folded into relationships owned by the atomic component that holds
                # the resulting record (see relationships below)
                userModule                  = component "User Module" "Owns user accounts, roles, and login/JWT issuance." "Python module" "Atomic Module"
                eventModule                 = component "Event Module" "Owns the Event entity and coordinates the coordinator-assignment and change/cancellation workflows." "Python module" "Atomic Module"
                venueModule                 = component "Venue Module" "Owns the venue catalogue and the suitability-check computation." "Python module" "Atomic Module"
                bookingConflictModule       = component "Booking Conflict Module" "Owns the conflict-detection algorithm for a venue and time window." "Python module" "Atomic Module"
                venueAvailabilitiesModule   = component "Venue Availabilities Module" "Owns venue booking records and coordinates the venue-booking workflow." "Python module" "Atomic Module"
                equipmentModule             = component "Equipment Module" "Owns the equipment catalogue only — no reservation data." "Python module" "Atomic Module"
                equipmentAvailabilityModule = component "Equipment Availability Module" "Owns equipment reservation records and coordinates the equipment-reservation workflow." "Python module" "Atomic Module"
                registrationModule          = component "Registration Module" "Owns attendee registration records and coordinates the attendee registration/withdrawal workflow." "Python module" "Atomic Module"
                notificationModule          = component "Notification Module" "Owns notification records and delivers email/SMS alerts." "Python module" "Atomic Module"
                forumModule                 = component "Forum / Communication Module" "Owns all communication tied to a request, such as clarifications and decision reasons." "Python module" "Atomic Module NoSQL"
            }

            messageBroker = container "Message Broker" "The only asynchronous path in the system — modules publish notification events here; the Notification Module consumes them." "RabbitMQ" "Message Broker"
        }

        # ================= Relationships =================

        # Front-End App -> entry-point modules
        connectSphere.frontEndApp -> connectSphere.apiApplication.eventModule "Creates/edits/cancels events, and assigns coordinators, using" "HTTPS/JSON"
        connectSphere.frontEndApp -> connectSphere.apiApplication.venueAvailabilitiesModule "Submits & manages venue bookings using" "HTTPS/JSON"
        connectSphere.frontEndApp -> connectSphere.apiApplication.equipmentAvailabilityModule "Submits & manages equipment requests using" "HTTPS/JSON"
        connectSphere.frontEndApp -> connectSphere.apiApplication.registrationModule "Registers/withdraws attendees using" "HTTPS/JSON"

        # Event Module — owns coordinator-assignment + change/cancellation workflows
        connectSphere.apiApplication.eventModule -> connectSphere.apiApplication.userModule "Looks up eligible coordinators from (coordinator assignment)"
        connectSphere.apiApplication.eventModule -> connectSphere.apiApplication.bookingConflictModule "Re-checks venue conflicts via (event change)"
        connectSphere.apiApplication.eventModule -> connectSphere.apiApplication.equipmentAvailabilityModule "Re-checks equipment commitments via (event change)"
        connectSphere.apiApplication.eventModule -> connectSphere.apiApplication.forumModule "Logs assignment/change/cancellation reasons to"
        connectSphere.apiApplication.eventModule -> connectSphere.messageBroker "Publishes coordinator-assigned & event-changed notifications to" "AMQP (async)"

        # Venue Availabilities Module — owns the venue-booking workflow
        connectSphere.apiApplication.venueAvailabilitiesModule -> connectSphere.apiApplication.eventModule "Reads event details from"
        connectSphere.apiApplication.venueAvailabilitiesModule -> connectSphere.apiApplication.venueModule "Checks venue suitability via"
        connectSphere.apiApplication.venueAvailabilitiesModule -> connectSphere.apiApplication.bookingConflictModule "Checks for double-booking via"
        connectSphere.apiApplication.venueAvailabilitiesModule -> connectSphere.apiApplication.forumModule "Logs the approval/rejection reason to"
        connectSphere.apiApplication.venueAvailabilitiesModule -> connectSphere.messageBroker "Publishes booking-decision notifications to" "AMQP (async)"

        # Equipment Availability Module — owns the equipment-reservation workflow
        connectSphere.apiApplication.equipmentAvailabilityModule -> connectSphere.apiApplication.eventModule "Reads event details from"
        connectSphere.apiApplication.equipmentAvailabilityModule -> connectSphere.apiApplication.forumModule "Logs the approval/rejection reason to"
        connectSphere.apiApplication.equipmentAvailabilityModule -> connectSphere.messageBroker "Publishes equipment-decision notifications to" "AMQP (async)"

        # Registration Module — owns the attendee registration/withdrawal workflow
        connectSphere.apiApplication.registrationModule -> connectSphere.apiApplication.eventModule "Validates the event is open for registration via"
        connectSphere.apiApplication.registrationModule -> connectSphere.messageBroker "Publishes registration-confirmed notifications to" "AMQP (async)"

        # Notification Module — consumes the broker, delivers directly
        connectSphere.apiApplication.notificationModule -> connectSphere.messageBroker "Consumes notification events from" "AMQP (async)"
        connectSphere.apiApplication.notificationModule -> emailProvider "Sends email/SMS via" "HTTPS"

        # Atomic modules -> data stores (cloud-hosted, outside the system boundary)
        connectSphere.apiApplication.userModule -> supabase "Authenticates users & reads/writes accounts in" "HTTPS/SQL"
        connectSphere.apiApplication.eventModule -> supabase "Reads/writes event records in" "HTTPS/SQL"
        connectSphere.apiApplication.venueModule -> supabase "Reads/writes venue catalogue in" "HTTPS/SQL"
        connectSphere.apiApplication.bookingConflictModule -> supabase "Reads booking windows from" "HTTPS/SQL"
        connectSphere.apiApplication.venueAvailabilitiesModule -> supabase "Reads/writes booking records in" "HTTPS/SQL"
        connectSphere.apiApplication.equipmentModule -> supabase "Reads/writes equipment catalogue in" "HTTPS/SQL"
        connectSphere.apiApplication.equipmentAvailabilityModule -> supabase "Reads/writes reservation records in" "HTTPS/SQL"
        connectSphere.apiApplication.registrationModule -> supabase "Reads/writes registration records in" "HTTPS/SQL"
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
            element "Atomic Module" {
                background #ffdc4a
                color #1a1a1a
                shape component
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
