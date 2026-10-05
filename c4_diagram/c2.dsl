/*
 * ConnectSphere — C2 Container diagram (Structurizr DSL)
 *
 * One Front-End App, one API Application wrapping every backend service,
 * a Hold Checker (a small scheduled job that only triggers the API once a
 * minute; the API does the hold expiry and publishes the 3-day reminder),
 * and a Message Broker for asynchronous in-app notifications, and the two
 * cloud-hosted databases kept OUTSIDE the system boundary (external
 * systems, not containers) — Supabase and MongoDB Atlas.
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
        lead = person "Event Coordinator Lead" "Internal staff who oversees incoming event requests and assigns coordinators." {
            tags "Internal"
        }
        vs = person "Venue Staff" "Internal staff who manages spaces and approves bookings." {
            tags "Internal"
        }
        ts = person "Technical Support Staff" "Internal staff who manages equipment requests." {
            tags "Internal"
        }
        so = person "Safety Officer" "Internal staff who reviews the operational safety of planned events." {
            tags "Internal"
        }

        # ---- External systems — cloud-hosted, kept outside the system boundary ----
        supabase = softwareSystem "Supabase" "Stores user accounts and relational data for the backend." "External System"
        mongodb  = softwareSystem "MongoDB Atlas" "Stores unstructured forum/communication records." "External System"

        # ---- ConnectSphere system boundary ----
        connectSphere = softwareSystem "ConnectSphere" "Event Planning and Venue Booking System." "ConnectSphere System" {

            frontEndApp = container "Front-End App" "GUI for submitting, reviewing, and managing events, bookings, registrations, and safety checks." "React, TypeScript, Vite" "Web Application"

            apiApplication = container "API Application" "Backend REST API handling event, venue, equipment, registration, and safety-check business logic." "Python, Flask" "Backend Application"

            holdChecker = container "Hold Checker" "Runs every minute and asks the API to expire holds that have run out and to send the 3-day reminder. Holds no logic or data of its own." "Python scheduled job" "Background Job"

            messageBroker = container "Message Broker" "Carries asynchronous notification events from the backend modules to the Notification Module; messages are durable and de-duplicated." "RabbitMQ" "Message Broker"
        }

        # ================= Relationships =================

        eo       -> connectSphere.frontEndApp "Submits and manages event requests using" "HTTPS"
        attendee -> connectSphere.frontEndApp "Registers for events using" "HTTPS"
        ec       -> connectSphere.frontEndApp "Plans events, books venues and equipment, and submits safety checks using" "HTTPS"
        lead     -> connectSphere.frontEndApp "Views the unassigned queue, assigns and reassigns coordinators using" "HTTPS"
        vs       -> connectSphere.frontEndApp "Manages venues and holds, and approves venue requests using" "HTTPS"
        ts       -> connectSphere.frontEndApp "Approves equipment requests using" "HTTPS"
        so       -> connectSphere.frontEndApp "Reviews and decides safety checks using" "HTTPS"

        connectSphere.frontEndApp -> connectSphere.apiApplication "Makes API calls (including notification polling) to" "HTTPS/JSON"

        connectSphere.apiApplication -> supabase "Authenticates users & reads/writes relational data in" "HTTPS/SQL"
        connectSphere.apiApplication -> mongodb "Reads/writes NoSQL communication entries in" "TCP"

        # Asynchronous relationships
        connectSphere.apiApplication -> connectSphere.messageBroker "Publishes and consumes notifications via" "AMQP" {
            tags "Async"
        }

        # Hold Checker — only a timer: it triggers the API (never a database or the broker directly);
        # the API expires the holds and publishes the reminders through the broker above
        connectSphere.holdChecker -> connectSphere.apiApplication "Every minute, triggers hold expiry and the 3-day reminder check on" "HTTPS/JSON"
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
            element "Background Job" {
                background #85bbf0
                color #000000
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