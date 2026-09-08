from app import db
from app.models.customer import Customer


class CustomerService:
    @staticmethod
    def get_all():
        return [
            {"id": c.id, "name": c.name, "email": c.email, "color_hex": c.color_hex}
            for c in Customer.query.order_by(Customer.name).all()
        ]

    @staticmethod
    def create(data):
        name = data.get("name", "").strip()
        if not name:
            return {"error": "Name ist erforderlich."}, 400
        customer = Customer(
            name=name,
            email=data.get("email", "").strip(),
            color_hex=data.get("color_hex", "#2B6CB0").strip(),
        )
        db.session.add(customer)
        db.session.commit()
        return {"message": "Kunde erfolgreich angelegt.", "id": customer.id}, 201

    @staticmethod
    def update(c_id, data):
        c = db.session.get(Customer, c_id)
        if not c:
            return {"error": "Kunde nicht gefunden."}, 404
        name = data.get("name", c.name).strip()
        if not name:
            return {"error": "Name ist erforderlich."}, 400
        c.name = name
        c.email = data.get("email", c.email).strip() if "email" in data else c.email
        c.color_hex = (
            data.get("color_hex", c.color_hex).strip()
            if "color_hex" in data
            else c.color_hex
        )
        db.session.commit()
        return {"message": "Kunde aktualisiert.", "id": c.id}, 200

    @staticmethod
    def delete(c_id):
        c = db.session.get(Customer, c_id)
        if not c:
            return {"error": "Kunde nicht gefunden."}, 404
        db.session.delete(c)
        db.session.commit()
        return {"message": "Kunde gelöscht."}, 200
