/*
 * ConnectSphere — C2 Container diagram (Structurizr DSL)
 *
 * One Front-End App, one API Application wrapping every backend service,
 * and a Message Broker for asynchronous notifications,
 * and the two cloud-hosted databases kept OUTSIDE the system boundary
 * (external systems, not containers) — Supabase and MongoDB Atlas.
 */

workspace "ConnectSphere" "C2 — Containers" {

    !identifiers hierarchical

    model {

        # --- Actors ---
        eo = person "Event Organiser" "External client who submits and manages event requests." {
            tags "External"
        }
        attendee = person "Attendee" "External user who registers for confirmed events." {
            tags "External"
        }
        ec = person "Event Coordinator" "Internal staff who coordinates the event lifecycle." {
            tags "Internal"
        }
        vs = person "Venue Staff" "Internal staff who manages spaces and approves bookings." {
            tags "Internal"
        }
        ts = person "Technical Staff" "Internal staff who manages equipment requests." {
            tags "Internal"
        }

        # ---- External systems — cloud-hosted, kept outside the system boundary ----
        supabase = softwareSystem "Supabase" "Stores user accounts and relational data for the backend." "External System"
        mongodb  = softwareSystem "MongoDB Atlas" "Stores unstructured forum/communication records." "External System"
        emailProvider = softwareSystem "Notification Service" "External service for sending email/SMS alerts." "External System"

        # ---- ConnectSphere system boundary ----
        connectSphere = softwareSystem "ConnectSphere" "Event Planning and Venue Booking System." "ConnectSphere System" {

            frontEndApp = container "Front-End App" "GUI for submitting, reviewing, and managing events, bookings, and registrations." "React, TypeScript, Vite" "Web Application"

            apiApplication = container "API Application" "Backend REST API handling event, venue, equipment, and registration business logic." "Python, Flask" "Backend Application"

            messageBroker = container "Message Broker" "Carries asynchronous notification events between backend modules." "RabbitMQ" "Message Broker"
        }

        # ================= Relationships =================

        eo       -> connectSphere.frontEndApp "Submits and manages event requests using" "HTTPS"
        attendee -> connectSphere.frontEndApp "Registers for events using" "HTTPS"
        ec       -> connectSphere.frontEndApp "Manages planning & venue searches using" "HTTPS"
        vs       -> connectSphere.frontEndApp "Approves venue requests using" "HTTPS"
        ts       -> connectSphere.frontEndApp "Approves equipment requests using" "HTTPS"

        connectSphere.frontEndApp -> connectSphere.apiApplication "Makes API calls to" "HTTPS/JSON"

        connectSphere.apiApplication -> supabase "Authenticates users & reads/writes relational data in" "HTTPS/SQL"
        connectSphere.apiApplication -> mongodb "Reads/writes NoSQL communication entries in" "TCP"
        connectSphere.apiApplication -> emailProvider "Dispatches notifications using" "HTTPS"

        # New asynchronous relationship
        connectSphere.apiApplication -> connectSphere.messageBroker "Publishes and consumes notifications via" "AMQP" {
            tags "Async"
        }
    }

    views {

        container connectSphere "C2-Containers" {
            include *
            autoLayout lr 400 150
            title "ConnectSphere — Containers (C2)"
        }

        styles {
            element "Person" {
                shape person
                fontSize 22
            }
            element "External" {
                background #999999
                color #ffffff
            }
            element "Internal" {
                background #0b3d6e
                color #ffffff
            }
            element "External System" {
                background #999999
                color #ffffff
                shape cylinder
            }
            element "ConnectSphere System" {
                background #ffffff
                color #1a1a1a
            }
            element "Boundary:SoftwareSystem" {
                stroke #0b3d6e
                strokeWidth 3
                border dashed
                color #0b3d6e
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
            element "Message Broker" {
                background #dedaff
                color #6631d7
                shape pipe
            }
            relationship "Relationship" {
                color #707070
                thickness 2
                style dashed
                routing Direct
                fontSize 20
                width 350
            }
            relationship "Async" {
                color #6631d7
                thickness 2
                style dashed
            }
        }
    }
}